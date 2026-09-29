"""Authentication, role, reference-existence, request-shape and check-ordering
behaviour of the CLE accreditation API.

Every test builds its own state from an empty register, with the logical clock
at its default instant of 2026-08-01T00:00:00Z.
"""
from datetime import datetime, timedelta

from test_helpers import (
    TEST_USERS,
    accreditation_action,
    accreditation_action_payload,
    api_client,
    assert_attendance_report,
    assert_version_unchanged,
    build_user_headers,
    create_accredited_provider,
    create_attendance_report_payload,
    create_attorney,
    create_course_payload,
    create_credit_record_payload,
    create_probationary_provider,
    create_provider,
    create_self_certified_course,
    credit_allocation_entry,
    disposition_payload,
    file_complaint,
    list_allocations,
    list_attendance_reports,
    list_credit_records,
    list_courses,
    list_fee_assessments,
    make_attorney_headers,
    make_board_admin_headers,
    make_provider_admin_headers,
    read_application,
    read_attorney,
    read_complaint,
    read_course,
    read_cycle,
    read_fee_assessment,
    read_provider,
    review_action_payload,
    roster_entry,
    settlement_payload,
    setup_attorney_with_cycle,
    submit_application,
    validate_error,
    validate_success,
)

# An identifier of the right shape that names nothing in the register.
UNKNOWN_ID = "00000000-0000-4000-8000-00000000dead"

BOARD = TEST_USERS["board_admin_headers"]
REVIEWER = TEST_USERS["accreditation_reviewer_headers"]

# The logical clock starts every test here.
CLOCK_START = "2026-08-01T00:00:00Z"

# A session whose hard filing window of session_date plus 90 days closed on
# 2026-06-30T09:00:00Z, before the clock instant every test starts from.
STALE_SESSION_DATE = "2026-04-01T09:00:00Z"

# A session inside its filing window: 17 days before the clock instant, so
# still short of the due date of session_date plus 30 days.
OPEN_SESSION_DATE = "2026-07-15T09:00:00Z"


def parse_instant(value: str) -> datetime:
    """Reads an ISO-8601 UTC instant, so timestamps compare by value rather
    than by rendering."""
    assert isinstance(value, str) and value.endswith("Z"), (
        f"expected a UTC instant ending in Z, got {value!r}"
    )
    return datetime.fromisoformat(value[:-1].replace("+00:00", ""))


def minutes_after(instant: str, minutes: int) -> datetime:
    """The instant reached by adding a whole number of minutes."""
    return parse_instant(instant) + timedelta(minutes=minutes)


def allocation_pairs(course_id: str):
    """The course's category allocations as an unordered set of pairs."""
    return {(row["category"], row["minutes"]) for row in list_allocations(course_id)}


def roster_course(provider, session_date):
    """A self-certified live course committed to roster verification, whose
    session begins at the given instant."""
    return create_self_certified_course(
        provider,
        title="Courtroom Technology Lab",
        delivery_format="LIVE_IN_PERSON",
        total_minutes=120,
        presented_at=session_date,
        attendance_verification_method="ROSTER",
        credit_allocations=[credit_allocation_entry("TECHNOLOGY", 120)],
    )


def test_unauthenticated_headers_are_refused_before_anything_else_is_examined():
    """Every request — read or write — must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming that principal's role.
    If either header is absent or empty, or if `X-User-Role` does not name one of the five declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else is examined.
    **Authentication.** `X-User-Role` present and naming one of the five declared roles, and `X-User-ID` present and non-empty — otherwise `ERR_UNAUTHENTICATED` (401). Applies to every endpoint.
    This order is normative: it is what makes an error response predictable, and it is why, for example, a request from an unauthorized role against a non-existent resource returns a permission error rather than a not-found error.

    Design: Corner/validations/missing_and_unknown_auth_headers_are_refused_unauthenticated_before_any_other_check
    """
    # No headers at all, against a provider identifier that resolves to
    # nothing: the 401 arrives instead of the not-found this path would
    # otherwise produce (PRD §2.8).
    validate_error(api_client.get_provider(UNKNOWN_ID, {}), "ERR_UNAUTHENTICATED")

    # A role string that names none of the five declared roles, carried on a
    # body that is itself malformed in two ways.
    validate_error(
        api_client.create_provider(
            {"name": "", "provider_type": "NOT_A_TYPE"},
            build_user_headers("clerk-unknown", "NOT_A_ROLE"),
        ),
        "ERR_UNAUTHENTICATED",
    )

    # An empty X-User-ID beside a role that is declared.
    validate_error(
        api_client.create_reporting_sweep(build_user_headers("", "BoardAdmin")),
        "ERR_UNAUTHENTICATED",
    )


def test_a_forbidden_role_is_refused_before_the_unknown_path_id_is_looked_up():
    """When the headers are well formed but the named role is not among the roles the addressed endpoint permits, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403).
    **Authorization.** The acting role appears in the endpoint's permitted roles, and where a shared endpoint reserves an action for one role the acting role owns that action — otherwise `ERR_ROLE_NOT_PERMITTED` (403). Applies to every endpoint.
    **Path resource existence**, validated left to right along the path template: a provider identifier that resolves to nothing yields `ERR_PROVIDER_NOT_FOUND`, a course `ERR_COURSE_NOT_FOUND`, a course application `ERR_APPLICATION_NOT_FOUND`, an attorney `ERR_ATTORNEY_NOT_FOUND`, a compliance cycle `ERR_CYCLE_NOT_FOUND`, a credit record `ERR_CREDIT_RECORD_NOT_FOUND`, a reciprocity claim `ERR_RECIPROCITY_CLAIM_NOT_FOUND`, an audit `ERR_AUDIT_NOT_FOUND`, a complaint `ERR_COMPLAINT_NOT_FOUND`, a fee assessment `ERR_FEE_ASSESSMENT_NOT_FOUND` — all HTTP 404.
    This order is normative: it is what makes an error response predictable, and it is why, for example, a request from an unauthorized role against a non-existent resource returns a permission error rather than a not-found error.
    Six board actions drive the sponsor forward and backward: `GRANT_FULL`, `GRANT_PROBATIONARY`, `DENY`, `RENEW`, `SUSPEND` and `REINSTATE`.

    Design: Corner/validations/a_forbidden_role_is_refused_before_the_unknown_path_id_is_looked_up
    """
    provider = create_provider(
        name="Meridian Continuing Studies", provider_type="LAW_SCHOOL"
    )
    payload = accreditation_action_payload("GRANT_FULL", provider["version"])

    # A sponsor administrator on an accreditation action against an unknown
    # sponsor: the permission verdict precedes the path lookup.
    validate_error(
        api_client.provider_accreditation_action(
            UNKNOWN_ID, payload, make_provider_admin_headers(UNKNOWN_ID)
        ),
        "ERR_ROLE_NOT_PERMITTED",
    )

    # The same request from the board reaches the path lookup and the 404.
    validate_error(
        api_client.provider_accreditation_action(UNKNOWN_ID, payload, BOARD),
        "ERR_PROVIDER_NOT_FOUND",
    )

    after = read_provider(provider["id"])
    assert after["accreditation_status"] == "APPLIED"
    assert_version_unchanged(provider, after)


def test_a_forbidden_role_is_refused_before_the_malformed_body_is_examined():
    """When the headers are well formed but the named role is not among the roles the addressed endpoint permits, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403).
    **Authorization.** The acting role appears in the endpoint's permitted roles, and where a shared endpoint reserves an action for one role the acting role owns that action — otherwise `ERR_ROLE_NOT_PERMITTED` (403). Applies to every endpoint.
    **Request shape.** Every required input present and well formed: enums take a declared value, minute counts are non-negative integers, `origin_credit_hours` is a positive number with at most one decimal place, `period_start` is strictly earlier than `period_end`, `session_date` is a date, `action` names an action the endpoint declares, and `credit_allocations` is a non-empty array whose `category` values are all distinct — otherwise `ERR_INVALID_REQUEST` (422). Applies to every write endpoint.
    An attorney claims credit for one attended course at a time.

    Design: Corner/validations/a_forbidden_role_is_refused_before_the_unknown_path_id_is_looked_up
    """
    # A reviewer filing an attendance claim: the claim endpoint is the
    # attorney's own, so the 403 arrives before the two unknown references and
    # before the undeclared enum, the negative minutes and the unparsable date.
    validate_error(
        api_client.create_credit_record(
            {
                "attorney_id": UNKNOWN_ID,
                "course_id": UNKNOWN_ID,
                "verification_method": "NOT_A_METHOD",
                "attended_minutes": -5,
                "completion_date": "not-a-date",
            },
            REVIEWER,
        ),
        "ERR_ROLE_NOT_PERMITTED",
    )

    assert list_credit_records() == [], "a refused claim must persist nothing"


def test_an_unknown_body_foreign_key_outranks_an_invalid_enum_in_the_same_request():
    """**Body foreign-key existence**, validated in the order the fields appear in the endpoint's input: `provider_id`, `course_id`, `attorney_id`, `cycle_id`, `attendance_report_id`, `reciprocity_claim_id`, `affirmation_id`, `previous_cycle_id`, `originating_complaint_id`.
    Each unresolved reference yields its own not-found code from the list above (HTTP 404).
    **Request shape.** Every required input present and well formed: enums take a declared value, minute counts are non-negative integers, `origin_credit_hours` is a positive number with at most one decimal place, `period_start` is strictly earlier than `period_end`, `session_date` is a date, `action` names an action the endpoint declares, and `credit_allocations` is a non-empty array whose `category` values are all distinct — otherwise `ERR_INVALID_REQUEST` (422). Applies to every write endpoint.
    The claim names `attorney_id` (which must equal the acting `X-User-ID`), the `course_id` attended, the `verification_method` being relied on, the `attended_minutes` actually sat through (greater than zero), and the `completion_date` — the instant attendance finished.

    Design: Corner/validations/an_unknown_body_foreign_key_outranks_an_invalid_enum_in_the_same_request
    """
    provider = create_accredited_provider(name="Vantage Bar Education")
    course = create_self_certified_course(provider)
    attorney = create_attorney(bar_number="V3-0001", full_name="Dana Okonjo")
    headers = make_attorney_headers(attorney["id"])

    # An unknown attorney reference beside an undeclared enum value: the
    # reference decides the answer (PRD §2.8).
    validate_error(
        api_client.create_credit_record(
            create_credit_record_payload(
                UNKNOWN_ID,
                course["id"],
                verification_method="NOT_A_METHOD",
                attended_minutes=600,
                completion_date="2026-07-01T00:00:00Z",
            ),
            headers,
        ),
        "ERR_ATTORNEY_NOT_FOUND",
    )

    # An unknown course reference beside the same undeclared enum value.
    validate_error(
        api_client.create_credit_record(
            create_credit_record_payload(
                attorney["id"],
                UNKNOWN_ID,
                verification_method="NOT_A_METHOD",
                attended_minutes=600,
                completion_date="2026-07-01T00:00:00Z",
            ),
            headers,
        ),
        "ERR_COURSE_NOT_FOUND",
    )

    assert list_credit_records() == [], "neither refusal may create a record"
    assert_version_unchanged(attorney, read_attorney(attorney["id"]))


def test_a_stale_provider_version_outranks_the_undeclared_transition_it_would_attempt():
    """`POST /cle/providers/{id}/accreditation-actions` requires `expected_provider_version`, carrying the client's last observed `version` of the target `Provider`.
    If it does not equal that provider's current `version`, the action is rejected with `ERR_STALE_VERSION` (HTTP 412).
    **Optimistic concurrency.** Where the endpoint declares a version input, its value equals the current `version` of the parent row — otherwise `ERR_STALE_VERSION` (412), on the three endpoints listed in §2.6.
    **State preconditions.** The addressed resource is in a state from which the requested trigger is declared, and every cross-entity state precondition of that transition holds — otherwise `ERR_INVALID_STATE_TRANSITION` (409).
    `DENIED` is the sponsor's only terminal state; no action leads out of it.
    Most resources also carry an `updated_at` timestamp, refreshed on every mutation of that row, and an integer `version` that starts at 1 on creation and increases by exactly 1 on every mutation of that row — including mutations the row did not ask for, such as a counter bump driven by a cascade from another entity.

    Design: Corner/validations/a_stale_provider_version_outranks_the_undeclared_transition_it_would_attempt
    """
    provider = create_provider(
        name="Lakeshore Advocacy Institute", provider_type="COMMERCIAL"
    )
    denied = accreditation_action(
        provider["id"],
        "DENY",
        provider["version"],
        probation_reason="Faculty roster was never produced.",
    )
    assert denied["accreditation_status"] == "DENIED"

    # Doubly wrong: the pre-denial version, and a transition the terminal state
    # does not declare. The concurrency guard decides it.
    validate_error(
        api_client.provider_accreditation_action(
            provider["id"],
            accreditation_action_payload("GRANT_PROBATIONARY", provider["version"]),
            BOARD,
        ),
        "ERR_STALE_VERSION",
    )

    # The identical body with the current version now reaches the state check.
    validate_error(
        api_client.provider_accreditation_action(
            provider["id"],
            accreditation_action_payload("GRANT_PROBATIONARY", denied["version"]),
            BOARD,
        ),
        "ERR_INVALID_STATE_TRANSITION",
    )

    after = read_provider(provider["id"])
    assert after["accreditation_status"] == "DENIED"
    assert_version_unchanged(denied, after)


def live_course_payload(provider, title, allocations, total_minutes=600):
    """A 600-minute live course of one sponsor, split across the given
    category allocations."""
    return create_course_payload(
        title=title,
        delivery_format="LIVE_IN_PERSON",
        total_minutes=total_minutes,
        presented_at="2026-09-01T09:00:00Z",
        attendance_verification_method="ROSTER",
        credit_allocations=allocations,
        provider_id=provider["id"],
    )


def test_a_repeated_allocation_category_is_refused_before_the_sum_is_totalled():
    """The array must be non-empty and no category may appear twice; an empty array or a repeated category is `ERR_INVALID_REQUEST`.
    The allocated minutes must sum exactly to `total_minutes`; a mismatch in either direction is `ERR_ALLOCATION_SUM_MISMATCH`, and an element whose `minutes` is not a positive multiple of 15 is `ERR_ALLOCATION_NOT_MULTIPLE_OF_15`.
    **Request shape.** Every required input present and well formed: enums take a declared value, minute counts are non-negative integers, `origin_credit_hours` is a positive number with at most one decimal place, `period_start` is strictly earlier than `period_end`, `session_date` is a date, `action` names an action the endpoint declares, and `credit_allocations` is a non-empty array whose `category` values are all distinct — otherwise `ERR_INVALID_REQUEST` (422). Applies to every write endpoint.
    **Uniqueness, cardinality and sum constraints**, all HTTP 409: `ERR_DUPLICATE_CREDIT_RECORD`, `ERR_DUPLICATE_APPLICATION`, `ERR_DUPLICATE_BAR_NUMBER`, `ERR_ALLOCATION_SUM_MISMATCH`, `ERR_ALLOCATION_NOT_MULTIPLE_OF_15`, `ERR_BELOW_MINIMUM_CREDIT`, `ERR_EMPTY_ROSTER`, `ERR_NO_SAMPLE_POPULATION`, `ERR_INFO_REQUEST_LIMIT_EXCEEDED`, `ERR_REMAND_LIMIT_EXCEEDED`, `ERR_FINDINGS_EXCEED_SAMPLE`, `ERR_COMPLAINT_ALREADY_ESCALATED`, `ERR_VERIFICATION_METHOD_NOT_PERMITTED`, `ERR_ATTENDANCE_CODE_INVALID`, `ERR_AFFIRMATION_REQUIRED`, `ERR_COMITY_NOT_AVAILABLE` and `ERR_JURISDICTION_NOT_RECIPROCAL`.
    When a single request violates several rules, the response must name the violation that comes first in the following order.

    Design: Corner/validations/course_allocations_are_checked_as_a_set_for_distinctness_then_sum_then_increment
    """
    provider = create_accredited_provider(name="County Bar Association")
    headers = make_provider_admin_headers(provider["id"])

    # Two GENERAL rows, and the array also sums to 500 against a declared 600:
    # the shape verdict is the one that arrives (PRD §2.8).
    validate_error(
        api_client.create_course(
            live_course_payload(
                provider,
                "Duplicate Category Split",
                [
                    credit_allocation_entry("GENERAL", 300),
                    credit_allocation_entry("GENERAL", 200),
                ],
            ),
            headers,
        ),
        "ERR_INVALID_REQUEST",
    )

    assert list_courses(provider_id=provider["id"]) == []
    assert read_provider(provider["id"])["courses_total_count"] == 0


def test_allocations_that_do_not_sum_to_total_minutes_are_refused():
    """The allocated minutes must sum exactly to `total_minutes`; a mismatch in either direction is `ERR_ALLOCATION_SUM_MISMATCH`, and an element whose `minutes` is not a positive multiple of 15 is `ERR_ALLOCATION_NOT_MULTIPLE_OF_15`.
    The accepted sum is stored on the course as `credited_minutes_total`, which is therefore always equal to `total_minutes`.
    **Uniqueness, cardinality and sum constraints**, all HTTP 409: `ERR_DUPLICATE_CREDIT_RECORD`, `ERR_DUPLICATE_APPLICATION`, `ERR_DUPLICATE_BAR_NUMBER`, `ERR_ALLOCATION_SUM_MISMATCH`, `ERR_ALLOCATION_NOT_MULTIPLE_OF_15`, `ERR_BELOW_MINIMUM_CREDIT`, `ERR_EMPTY_ROSTER`, `ERR_NO_SAMPLE_POPULATION`, `ERR_INFO_REQUEST_LIMIT_EXCEEDED`, `ERR_REMAND_LIMIT_EXCEEDED`, `ERR_FINDINGS_EXCEED_SAMPLE`, `ERR_COMPLAINT_ALREADY_ESCALATED`, `ERR_VERIFICATION_METHOD_NOT_PERMITTED`, `ERR_ATTENDANCE_CODE_INVALID`, `ERR_AFFIRMATION_REQUIRED`, `ERR_COMITY_NOT_AVAILABLE` and `ERR_JURISDICTION_NOT_RECIPROCAL`.

    Design: Corner/validations/course_allocations_are_checked_as_a_set_for_distinctness_then_sum_then_increment
    """
    provider = create_accredited_provider(name="County Bar Association")
    headers = make_provider_admin_headers(provider["id"])

    # Distinct categories, each a whole multiple of 15, but 300 + 195 is 495
    # rather than the declared 600.
    validate_error(
        api_client.create_course(
            live_course_payload(
                provider,
                "Short Sum Split",
                [
                    credit_allocation_entry("GENERAL", 300),
                    credit_allocation_entry("ETHICS", 195),
                ],
            ),
            headers,
        ),
        "ERR_ALLOCATION_SUM_MISMATCH",
    )

    assert list_courses(provider_id=provider["id"]) == []


def test_an_allocation_off_the_fifteen_minute_increment_is_refused():
    """The allocated minutes must sum exactly to `total_minutes`; a mismatch in either direction is `ERR_ALLOCATION_SUM_MISMATCH`, and an element whose `minutes` is not a positive multiple of 15 is `ERR_ALLOCATION_NOT_MULTIPLE_OF_15`.
    Every element of `credit_allocations` names a `category` — `GENERAL`, `ETHICS`, `TECHNOLOGY` or `BIAS_ELIMINATION` — and the `minutes` allocated to it, which must be greater than zero and a whole multiple of 15 minutes.
    **Uniqueness, cardinality and sum constraints**, all HTTP 409: `ERR_DUPLICATE_CREDIT_RECORD`, `ERR_DUPLICATE_APPLICATION`, `ERR_DUPLICATE_BAR_NUMBER`, `ERR_ALLOCATION_SUM_MISMATCH`, `ERR_ALLOCATION_NOT_MULTIPLE_OF_15`, `ERR_BELOW_MINIMUM_CREDIT`, `ERR_EMPTY_ROSTER`, `ERR_NO_SAMPLE_POPULATION`, `ERR_INFO_REQUEST_LIMIT_EXCEEDED`, `ERR_REMAND_LIMIT_EXCEEDED`, `ERR_FINDINGS_EXCEED_SAMPLE`, `ERR_COMPLAINT_ALREADY_ESCALATED`, `ERR_VERIFICATION_METHOD_NOT_PERMITTED`, `ERR_ATTENDANCE_CODE_INVALID`, `ERR_AFFIRMATION_REQUIRED`, `ERR_COMITY_NOT_AVAILABLE` and `ERR_JURISDICTION_NOT_RECIPROCAL`.

    Design: Corner/validations/course_allocations_are_checked_as_a_set_for_distinctness_then_sum_then_increment
    """
    provider = create_accredited_provider(name="County Bar Association")
    headers = make_provider_admin_headers(provider["id"])

    # The array sums to exactly 600, but neither 590 nor 10 lands on the
    # 15-minute increment.
    validate_error(
        api_client.create_course(
            live_course_payload(
                provider,
                "Off Increment Split",
                [
                    credit_allocation_entry("GENERAL", 590),
                    credit_allocation_entry("ETHICS", 10),
                ],
            ),
            headers,
        ),
        "ERR_ALLOCATION_NOT_MULTIPLE_OF_15",
    )

    assert list_courses(provider_id=provider["id"]) == []


def test_a_balanced_allocation_set_is_stored_as_the_courses_credited_total():
    """The accepted sum is stored on the course as `credited_minutes_total`, which is therefore always equal to `total_minutes`.
    Each element becomes an immutable allocation row bound to the new course by its `course_id`, and those rows are never editable afterwards.
    A course on the self-certification pathway is presumptively approved: it is created and immediately transitions `PENDING_APPROVAL → APPROVED` in the same request, its sponsor's `courses_self_certified_count` and `courses_total_count` each rise by one, and the sponsor's `risk_score` is recomputed because the denominator behind its findings rate has changed.
    Creation endpoints — those that bring a new row into existence — return HTTP 201; every other successful call, including every action endpoint that transitions an existing row and every read, returns HTTP 200.

    Design: Corner/validations/course_allocations_are_checked_as_a_set_for_distinctness_then_sum_then_increment
    """
    provider = create_accredited_provider(name="County Bar Association")
    headers = make_provider_admin_headers(provider["id"])

    response = api_client.create_course(
        live_course_payload(
            provider,
            "Balanced Split",
            [
                credit_allocation_entry("GENERAL", 450),
                credit_allocation_entry("ETHICS", 90),
                credit_allocation_entry("TECHNOLOGY", 60),
            ],
        ),
        headers,
    )
    course = validate_success(response, expected_status=201)

    assert course["credited_minutes_total"] == 600
    assert course["status"] == "APPROVED"
    assert allocation_pairs(course["id"]) == {
        ("GENERAL", 450),
        ("ETHICS", 90),
        ("TECHNOLOGY", 60),
    }

    sponsor = read_provider(provider["id"])
    assert sponsor["courses_total_count"] == 1
    assert sponsor["courses_self_certified_count"] == 1
    assert len(list_courses(provider_id=provider["id"])) == 1


def test_a_closed_roster_window_outranks_an_empty_entries_array():
    """The roster's `due_at` is `session_date` plus 30 days, and its hard close is `session_date` plus 90 days.
    A roster arriving after the hard close is refused outright with `ERR_ROSTER_WINDOW_CLOSED` and no roster row is written at all.
    The array must contain at least one element — an empty `entries` array is `ERR_EMPTY_ROSTER`.
    **Temporal coherence.** The credit's `completion_date` falls inside some cycle's half-open period (`ERR_OUTSIDE_COMPLIANCE_PERIOD`); the credit's `completion_date` does not exceed the course's `expires_at` (`ERR_COURSE_APPROVAL_EXPIRED`); a new cycle's half-open window does not overlap another cycle of the same attorney (`ERR_CYCLE_PERIOD_OVERLAP`); a new audit's closed window neither overlaps nor abuts another audit window of the same provider (`ERR_AUDIT_PERIOD_OVERLAP`) and the provider holds no other non-terminal audit (`ERR_AUDIT_ENGAGEMENT_ACTIVE`); a new live-in-person course does not push its provider's concurrent session count above the capacity limit (`ERR_SESSION_WINDOW_CONFLICT`); a roster arrives inside its hard filing window (`ERR_ROSTER_WINDOW_CLOSED`) — HTTP 409.
    When a single request violates several rules, the response must name the violation that comes first in the following order.

    Design: Corner/validations/a_closed_roster_window_outranks_an_empty_roster_and_a_missing_required_field
    """
    provider = create_accredited_provider(name="Old Mill Bar Center")
    course = roster_course(provider, STALE_SESSION_DATE)
    setup_attorney_with_cycle()

    # 122 days after the session, past the hard close of session_date plus 90
    # days, and the body is empty as well: the window verdict wins.
    validate_error(
        api_client.create_attendance_report(
            create_attendance_report_payload(course["id"], STALE_SESSION_DATE, []),
            make_provider_admin_headers(provider["id"]),
        ),
        "ERR_ROSTER_WINDOW_CLOSED",
    )

    assert list_attendance_reports(course["id"]) == [], "no roster row is written at all"
    assert read_provider(provider["id"])["attendance_reports_total_count"] == 0


def test_an_empty_entries_array_inside_the_filing_window_is_refused():
    """The array must contain at least one element — an empty `entries` array is `ERR_EMPTY_ROSTER`.
    The roster's `due_at` is `session_date` plus 30 days, and its hard close is `session_date` plus 90 days.
    **Uniqueness, cardinality and sum constraints**, all HTTP 409: `ERR_DUPLICATE_CREDIT_RECORD`, `ERR_DUPLICATE_APPLICATION`, `ERR_DUPLICATE_BAR_NUMBER`, `ERR_ALLOCATION_SUM_MISMATCH`, `ERR_ALLOCATION_NOT_MULTIPLE_OF_15`, `ERR_BELOW_MINIMUM_CREDIT`, `ERR_EMPTY_ROSTER`, `ERR_NO_SAMPLE_POPULATION`, `ERR_INFO_REQUEST_LIMIT_EXCEEDED`, `ERR_REMAND_LIMIT_EXCEEDED`, `ERR_FINDINGS_EXCEED_SAMPLE`, `ERR_COMPLAINT_ALREADY_ESCALATED`, `ERR_VERIFICATION_METHOD_NOT_PERMITTED`, `ERR_ATTENDANCE_CODE_INVALID`, `ERR_AFFIRMATION_REQUIRED`, `ERR_COMITY_NOT_AVAILABLE` and `ERR_JURISDICTION_NOT_RECIPROCAL`.

    Design: Corner/validations/a_closed_roster_window_outranks_an_empty_roster_and_a_missing_required_field
    """
    provider = create_accredited_provider(name="Old Mill Bar Center")
    course = roster_course(provider, OPEN_SESSION_DATE)
    setup_attorney_with_cycle()

    # The session is 17 days old, so the roster is inside both its due date and
    # its hard close; only the empty array is wrong.
    validate_error(
        api_client.create_attendance_report(
            create_attendance_report_payload(course["id"], OPEN_SESSION_DATE, []),
            make_provider_admin_headers(provider["id"]),
        ),
        "ERR_EMPTY_ROSTER",
    )

    assert list_attendance_reports(course["id"]) == []


def test_an_absent_entries_array_is_a_request_shape_failure():
    """**Request shape.** Every required input present and well formed: enums take a declared value, minute counts are non-negative integers, `origin_credit_hours` is a positive number with at most one decimal place, `period_start` is strictly earlier than `period_end`, `session_date` is a date, `action` names an action the endpoint declares, and `credit_allocations` is a non-empty array whose `category` values are all distinct — otherwise `ERR_INVALID_REQUEST` (422). Applies to every write endpoint.
    A `ProviderAdmin` may file a roster for one session of one of its own courses, supplying `course_id`, the `session_date` the session began, and an `entries` array whose elements each carry a `bar_number` and the `attended_minutes` that attendee sat through.
    The array must contain at least one element — an empty `entries` array is `ERR_EMPTY_ROSTER`.

    Design: Corner/validations/a_closed_roster_window_outranks_an_empty_roster_and_a_missing_required_field
    """
    provider = create_accredited_provider(name="Old Mill Bar Center")
    course = roster_course(provider, OPEN_SESSION_DATE)
    setup_attorney_with_cycle()

    # An absent array is a different verdict from a present but empty one.
    validate_error(
        api_client.create_attendance_report(
            {"course_id": course["id"], "session_date": OPEN_SESSION_DATE},
            make_provider_admin_headers(provider["id"]),
        ),
        "ERR_INVALID_REQUEST",
    )

    assert list_attendance_reports(course["id"]) == []


def test_a_roster_filed_before_its_due_date_is_accepted_and_cascades_credit():
    """A roster arriving at or before `due_at` has `days_late` of 0 and a `status` of `ACCEPTED`.
    On acceptance the roster stores `entry_count` (the number of rows supplied), `submitted_at` (the logical instant of acceptance) and `session_end`, which is `session_date` plus the course's `total_minutes` and marks the closed interval the session occupies on the course as a resource.
    `accepted_entry_count` counts the entries that produced a record and `rejected_entry_count` counts the rest, and the two always sum to `entry_count`.
    Each accepted entry cascades a credit record that is born `VERIFIED`, with `verification_method` set to `ROSTER` and `attendance_report_id` pointing at the roster, which raises the course's `verified_credit_record_count` and triggers a credit-application re-run for that record's owning cycle.
    A `LIVE_IN_PERSON` course always yields `LIVE`.
    A record with no cap pressure therefore contributes each of its four credited category figures in full.
    Every accepted roster, late or not, raises the sponsor's `attendance_reports_total_count` by one, and the sponsor's `risk_score` is recomputed afterwards.

    Design: Corner/validations/a_closed_roster_window_outranks_an_empty_roster_and_a_missing_required_field
    """
    provider = create_accredited_provider(name="Old Mill Bar Center")
    course = roster_course(provider, OPEN_SESSION_DATE)
    attorney, cycle = setup_attorney_with_cycle()

    response = api_client.create_attendance_report(
        create_attendance_report_payload(
            course["id"],
            OPEN_SESSION_DATE,
            [roster_entry(attorney["bar_number"], 120)],
        ),
        make_provider_admin_headers(provider["id"]),
    )
    report = validate_success(response, expected_status=201)
    assert_attendance_report(report)

    assert report["entry_count"] == 1
    assert report["accepted_entry_count"] == 1
    assert report["rejected_entry_count"] == 0
    assert report["days_late"] == 0
    assert report["status"] == "ACCEPTED"
    assert parse_instant(report["session_end"]) == minutes_after(OPEN_SESSION_DATE, 120)
    assert parse_instant(report["submitted_at"]) == parse_instant(CLOCK_START)

    cascaded = list_credit_records(attendance_report_id=report["id"])
    assert len(cascaded) == 1
    assert cascaded[0]["status"] == "VERIFIED"
    assert cascaded[0]["verification_method"] == "ROSTER"
    assert cascaded[0]["effective_format"] == "LIVE"
    assert read_course(course["id"])["verified_credit_record_count"] == 1
    assert read_cycle(cycle["id"])["earned_technology_minutes"] == 120

    sponsor = read_provider(provider["id"])
    assert sponsor["attendance_reports_total_count"] == 1
    assert sponsor["attendance_reports_late_count"] == 0


def individual_approval_course(provider):
    """A course of a sponsor that cannot self-certify, so it waits in
    PENDING_APPROVAL for an application to be decided."""
    return create_self_certified_course(
        provider,
        title="Legal Writing Intensive",
        delivery_format="LIVE_IN_PERSON",
        total_minutes=180,
        presented_at="2026-10-01T09:00:00Z",
        attendance_verification_method="ROSTER",
        credit_allocations=[credit_allocation_entry("GENERAL", 180)],
    )


def test_a_denial_without_a_denial_reason_is_an_invalid_request():
    """Denial moves the application to `DENIED` from either `SUBMITTED` or `INFO_REQUESTED`. A `denial_reason` must be supplied; without one the request is `ERR_INVALID_REQUEST`.
    The reason is recorded on the application, `denied_at` is stamped with the current logical instant, and the course cascades `PENDING_APPROVAL → DENIED` carrying the identical reason text into its own `denial_reason`.
    **Request shape.** Every required input present and well formed: enums take a declared value, minute counts are non-negative integers, `origin_credit_hours` is a positive number with at most one decimal place, `period_start` is strictly earlier than `period_end`, `session_date` is a date, `action` names an action the endpoint declares, and `credit_allocations` is a non-empty array whose `category` values are all distinct — otherwise `ERR_INVALID_REQUEST` (422). Applies to every write endpoint.
    **State preconditions.** The addressed resource is in a state from which the requested trigger is declared, and every cross-entity state precondition of that transition holds — otherwise `ERR_INVALID_STATE_TRANSITION` (409).

    Design: Corner/validations/conditionally_required_reasons_are_invalid_request_when_the_action_demands_them
    """
    provider = create_probationary_provider(name="Harbor Point Seminars")
    course = individual_approval_course(provider)
    application = submit_application(
        course["id"], make_provider_admin_headers(provider["id"])
    )
    assert application["status"] == "SUBMITTED"

    # The application sits in a state denial is declared from, so the missing
    # reason is the only defect.
    validate_error(
        api_client.application_review_action(
            application["id"], review_action_payload("DENY"), REVIEWER
        ),
        "ERR_INVALID_REQUEST",
    )

    reason = "The agenda documents no substantive legal content."
    decided = validate_success(
        api_client.application_review_action(
            application["id"],
            review_action_payload("DENY", denial_reason=reason),
            REVIEWER,
        ),
        expected_status=200,
    )
    assert decided["status"] == "DENIED"
    assert decided["denial_reason"] == reason
    assert decided["denied_at"] is not None
    assert read_application(application["id"])["status"] == "DENIED"

    denied_course = read_course(course["id"])
    assert denied_course["status"] == "DENIED"
    assert denied_course["denial_reason"] == reason


def test_a_dismissal_without_a_disposition_reason_is_an_invalid_request():
    """`DISMISS` is available from either `RECEIVED` or `UNDER_REVIEW`, requires a `disposition_reason`, and has no side effects beyond recording it.
    `OPEN_REVIEW` moves `RECEIVED → UNDER_REVIEW` and does nothing else.
    **Request shape.** Every required input present and well formed: enums take a declared value, minute counts are non-negative integers, `origin_credit_hours` is a positive number with at most one decimal place, `period_start` is strictly earlier than `period_end`, `session_date` is a date, `action` names an action the endpoint declares, and `credit_allocations` is a non-empty array whose `category` values are all distinct — otherwise `ERR_INVALID_REQUEST` (422). Applies to every write endpoint.
    Against a provider, the provider's `substantiated_complaint_count` rises by one, its `risk_score` is recomputed, and the provider itself moves `ACCREDITED → PROBATIONARY`.

    Design: Corner/validations/conditionally_required_reasons_are_invalid_request_when_the_action_demands_them
    """
    provider = create_probationary_provider(name="Harbor Point Seminars")
    complaint = file_complaint(
        "PROVIDER",
        provider["id"],
        filer_user_id="board-intake-11",
        allegation="Registration fees were charged twice.",
        allegation_category="FEE_DISPUTE",
    )

    # Opening the review carries no reason at all and is still accepted.
    opened = validate_success(
        api_client.complaint_disposition(
            complaint["id"],
            disposition_payload("OPEN_REVIEW"),
            make_board_admin_headers("board-review-12"),
        ),
        expected_status=200,
    )
    assert opened["status"] == "UNDER_REVIEW"

    # Dismissal from the same state demands the reason.
    validate_error(
        api_client.complaint_disposition(
            complaint["id"],
            disposition_payload("DISMISS"),
            make_board_admin_headers("board-review-12"),
        ),
        "ERR_INVALID_REQUEST",
    )

    reason = "The duplicate charge was refunded before the complaint was filed."
    dismissed = validate_success(
        api_client.complaint_disposition(
            complaint["id"],
            disposition_payload("DISMISS", disposition_reason=reason),
            make_board_admin_headers("board-review-12"),
        ),
        expected_status=200,
    )
    assert dismissed["status"] == "DISMISSED"
    assert dismissed["disposition_reason"] == reason
    assert read_complaint(complaint["id"])["status"] == "DISMISSED"

    sponsor = read_provider(provider["id"])
    assert sponsor["accreditation_status"] == "PROBATIONARY"
    assert sponsor["substantiated_complaint_count"] == 0


def test_a_waiver_without_a_waiver_reason_is_an_invalid_request():
    """`WAIVE` is reserved to the board alone and requires a `waiver_reason`; an attorney or a provider administrator requesting a waiver is rejected with `ERR_ROLE_NOT_PERMITTED` even though the endpoint itself admits their role.
    Either action stamps `settled_at` with the current instant, moves `status` to `PAID` or `WAIVED` accordingly, and — when the assessment names an `attorney_id` — lowers that attorney's `outstanding_fee_cents` by exactly this assessment's `amount_cents`.
    Both actions require the assessment to still be in `ASSESSED`; settling one already `PAID`, `WAIVED` or `VOIDED` is `ERR_FEE_ALREADY_SETTLED`.
    An assessment carries `amount_cents`, an `assessed_at` instant, a `status` of `ASSESSED`, `PAID`, `WAIVED` or `VOIDED` starting at `ASSESSED`, a `settled_at` instant recorded when it leaves `ASSESSED`, and a `waiver_reason` recorded only when it is waived.
    It stamps the same two-year term into `accreditation_term_start` and `accreditation_term_end`, leaves `self_certification_enabled` false, raises the same `PROVIDER_ANNUAL` assessment for `annual_fee_cents`, and re-scores the sponsor under `REVIEWED_WEIGHTING`.
    **Request shape.** Every required input present and well formed: enums take a declared value, minute counts are non-negative integers, `origin_credit_hours` is a positive number with at most one decimal place, `period_start` is strictly earlier than `period_end`, `session_date` is a date, `action` names an action the endpoint declares, and `credit_allocations` is a non-empty array whose `category` values are all distinct — otherwise `ERR_INVALID_REQUEST` (422). Applies to every write endpoint.

    Design: Corner/validations/conditionally_required_reasons_are_invalid_request_when_the_action_demands_them
    """
    provider = create_probationary_provider(name="Harbor Point Seminars")

    assessments = list_fee_assessments(provider_id=provider["id"])
    assert len(assessments) == 1
    assessment = assessments[0]
    assert assessment["fee_type"] == "PROVIDER_ANNUAL"
    assert assessment["status"] == "ASSESSED"

    # The assessment is still standing, so the missing reason is the only
    # defect in the waiver.
    validate_error(
        api_client.fee_settlement(
            assessment["id"], settlement_payload("WAIVE"), BOARD
        ),
        "ERR_INVALID_REQUEST",
    )

    reason = "Fee waived for a government co-sponsored term."
    settled = validate_success(
        api_client.fee_settlement(
            assessment["id"],
            settlement_payload("WAIVE", waiver_reason=reason),
            BOARD,
        ),
        expected_status=200,
    )
    assert settled["status"] == "WAIVED"
    assert settled["settled_at"] is not None
    assert settled["waiver_reason"] == reason
    assert read_fee_assessment(assessment["id"])["status"] == "WAIVED"
