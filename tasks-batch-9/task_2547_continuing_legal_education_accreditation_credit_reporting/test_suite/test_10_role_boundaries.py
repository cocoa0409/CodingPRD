"""Role boundaries: which seat may act, who owns the resource, and who is disqualified.

Every test builds its own register from scratch through the endpoints the PRD
declares, because the board's database is empty and its logical clock reads
2026-08-01T00:00:00Z when each test begins.
"""
from datetime import datetime, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    factories as f,
    fixtures as fx,
    make_attorney_headers,
    make_board_admin_headers,
    make_panelist_headers,
    make_provider_admin_headers,
    make_reviewer_headers,
    TEST_USERS,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

BOARD = TEST_USERS["board_admin_headers"]

CLOCK_START = "2026-08-01T00:00:00Z"
TERM_END_FROM_START = "2028-08-01T00:00:00Z"

REVIEWER_ID = "33333333-3333-4333-8333-333333333333"
PANELIST_ID = "44444444-4444-4444-8444-444444444444"
BOARD_FILER_ID = "11111111-1111-4111-8111-111111111111"
MISSING_ATTORNEY_ID = "00000000-0000-4000-8000-00000000dead"


def _instant(value: str) -> datetime:
    """Reads a wire timestamp so two spellings of one instant compare equal."""
    assert value is not None, "expected a timestamp, found null"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _same_instant(actual: str, expected: str) -> bool:
    return _instant(actual) == _instant(expected)


def _pending_course_with_application(provider_name, course_overrides=None):
    """A sponsor on probation, one course of its own awaiting board review, and
    that course's application filed by the sponsor itself.
    Returns (provider, course, application)."""
    provider = fx.create_probationary_provider(
        name=provider_name, provider_type="COMMERCIAL"
    )
    course = fx.create_self_certified_course(provider, **(course_overrides or {}))
    application = fx.submit_application(
        course["id"], make_provider_admin_headers(provider["id"])
    )
    return provider, course, application


def _appealed_application(provider_name, denial_reason, course_overrides=None,
                          reviewer_user_id=REVIEWER_ID):
    """One application denied by a named reviewer and then appealed by its own
    applicant. Returns (provider, course, application)."""
    provider, course, application = _pending_course_with_application(
        provider_name, course_overrides
    )
    application = fx.review_action(
        application["id"], "DENY", reviewer_user_id, denial_reason=denial_reason
    )
    application = fx.appellant_action(
        application["id"], "APPEAL",
        make_provider_admin_headers(provider["id"]),
        appeal_grounds="The filed materials answer the reviewer's concern in full.",
    )
    return provider, fx.read_course(course["id"]), application


def test_board_admin_alone_registers_sponsors_attorneys_and_periods(api, board_headers):
    """PRD 2.1: "**`BoardAdmin`** is state CLE board staff. It owns provider accreditation decisions, attorney registration and standing changes, compliance-period creation, reciprocity determinations, audits, complaint dispositions, credit adjudication, fee waivers, the reporting sweep and the logical clock."
    PRD 3.1: "The grant stamps `accreditation_term_start` with the current logical instant and `accreditation_term_end` with that instant plus 24 months, flips `self_certification_enabled` to true, raises a `PROVIDER_ANNUAL` assessment against the sponsor for exactly its `annual_fee_cents`, and re-scores it under the self-certified weighting, writing `risk_score_variant` as `SELF_CERTIFIED_WEIGHTING`."
    PRD 3.4: "A standing change leaves every one of that attorney's compliance cycles exactly as it found them: neither `credit_status` nor `administrative_status` moves, and the attorney's own `version` rises by one."

    Design: Corner/rbac/the_board_alone_drives_registration_standing_and_the_reporting_sweep
    """
    provider = fx.create_provider(
        name="Statehouse School of Law CLE Office", provider_type="LAW_SCHOOL"
    )
    assert provider["version"] == 1
    assert provider["accreditation_status"] == "APPLIED"

    granted = validate_success(
        api.provider_accreditation_action(
            provider["id"],
            {"action": "GRANT_FULL", "expected_provider_version": provider["version"]},
            board_headers,
        ),
        expected_status=200,
    )
    assert granted["accreditation_status"] == "ACCREDITED"
    assert granted["self_certification_enabled"] is True
    assert granted["risk_score_variant"] == "SELF_CERTIFIED_WEIGHTING"
    assert granted["version"] == 2
    assert _same_instant(granted["accreditation_term_start"], CLOCK_START)
    assert _same_instant(granted["accreditation_term_end"], TERM_END_FROM_START)

    attorney = validate_success(
        api.create_attorney(
            f.create_attorney_payload(
                bar_number="RBAC-100001",
                full_name="Marguerite Ellsworth",
                admission_date="2001-05-14T00:00:00Z",
                compliance_group="GROUP_2",
            ),
            board_headers,
        ),
        expected_status=201,
    )
    assert attorney["status"] == "ACTIVE"
    assert attorney["version"] == 1

    cycle = validate_success(
        api.create_compliance_cycle(
            attorney["id"],
            f.create_compliance_cycle_payload(
                period_start="2026-01-01T00:00:00Z",
                period_end="2028-01-01T00:00:00Z",
            ),
            board_headers,
        ),
        expected_status=201,
    )
    assert cycle["credit_status"] == "OPEN"
    assert cycle["administrative_status"] == "GOOD_STANDING"

    moved = validate_success(
        api.attorney_status_change(
            attorney["id"],
            {"status": "EXEMPT", "reason": "Full-time judicial appointment."},
            board_headers,
        ),
        expected_status=200,
    )
    assert moved["status"] == "EXEMPT"
    assert moved["version"] == 2

    after = fx.read_cycle(cycle["id"])
    assert after["credit_status"] == "OPEN"
    assert after["administrative_status"] == "GOOD_STANDING"


def test_board_admin_shared_writes_and_the_reporting_sweep_land_as_declared(api, board_headers):
    """PRD 3.2: "A `BoardAdmin` may register a course either way."
    PRD 3.2: "A course on the self-certification pathway is presumptively approved: it is created and immediately transitions `PENDING_APPROVAL → APPROVED` in the same request, its sponsor's `courses_self_certified_count` and `courses_total_count` each rise by one, and the sponsor's `risk_score` is recomputed because the denominator behind its findings rate has changed."
    PRD 3.9: "The complaint is created in `RECEIVED` with `escalated` false, and the filer is recorded in two fields — `complainant_role`, which takes the value `ATTORNEY` or `BOARD_ADMIN` (note that these are the recorded enumeration labels, not the header spellings of the roles), and `complainant_user_id`, which holds the acting `X-User-ID`."
    PRD 3.9: "Each run stamps `as_of` with the current logical instant and takes a `sweep_number` one higher than the previous run's, the first run being number 1."
    PRD 4: "Creation endpoints — those that bring a new row into existence — return HTTP 201; every other successful call, including every action endpoint that transitions an existing row and every read, returns HTTP 200."

    Design: Corner/rbac/the_board_alone_drives_registration_standing_and_the_reporting_sweep
    """
    provider = fx.create_accredited_provider(
        name="Cascade Bar Institute", provider_type="LAW_SCHOOL"
    )
    attorney = fx.create_attorney(
        bar_number="RBAC-100002",
        full_name="Delphine Okonkwo",
        admission_date="1999-09-09T00:00:00Z",
        compliance_group="GROUP_2",
    )
    fx.create_cycle(attorney["id"], "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z")

    course = validate_success(
        api.create_course(
            f.create_course_payload(
                provider_id=provider["id"],
                title="Judicial Ethics On Demand",
                delivery_format="ON_DEMAND",
                total_minutes=120,
                presented_at="2026-06-15T09:00:00Z",
                attendance_verification_method="CERTIFICATE",
                credit_allocations=[f.credit_allocation_entry("ETHICS", 120)],
            ),
            board_headers,
        ),
        expected_status=201,
    )
    assert course["status"] == "APPROVED"
    assert course["approval_pathway"] == "PROVIDER_ACCREDITED"

    sponsor = fx.read_provider(provider["id"])
    assert sponsor["courses_total_count"] == 1
    assert sponsor["courses_self_certified_count"] == 1

    complaint = validate_success(
        api.create_complaint(
            f.create_complaint_payload(
                subject_type="COURSE",
                subject_id=course["id"],
                allegation_category="NO_SHOW_FACULTY",
                allegation="The advertised faculty member never appeared on the recording.",
            ),
            make_board_admin_headers(BOARD_FILER_ID),
        ),
        expected_status=201,
    )
    assert complaint["status"] == "RECEIVED"
    assert complaint["escalated"] is False
    assert complaint["complainant_role"] == "BOARD_ADMIN"
    assert complaint["complainant_user_id"] == BOARD_FILER_ID

    validate_success(api.set_clock("2026-09-01T00:00:00Z", board_headers), expected_status=200)

    sweep = validate_success(api.create_reporting_sweep(board_headers), expected_status=201)
    assert sweep["sweep_number"] == 1
    assert _same_instant(sweep["as_of"], "2026-09-01T00:00:00Z")
    assert sweep["delinquencies_issued"] == 0
    assert sweep["suspensions_issued"] == 0
    assert sweep["late_fees_assessed_cents"] == 0
    assert sweep["courses_expired"] == 0
    assert sweep["providers_lapsed"] == 0


def test_reviewer_moves_carry_the_information_round_and_the_denial_stamp(api):
    """PRD 2.1: "**`AccreditationReviewer`** is the board reviewer who adjudicates individual course-approval applications, and nothing else on the write side."
    PRD 3.3: "An `AccreditationReviewer` acts on an application by naming an `action` of `REQUEST_INFO`, `APPROVE` or `DENY`, optionally with a `denial_reason`."
    PRD 3.3: "Two fields freeze the filer: `applicant_role` records which role filed and takes the value `PROVIDER_ADMIN` or `ATTORNEY`, and `applicant_user_id` records the filer's `X-User-ID`."
    PRD 3.3: "Whichever move is made, the acting `X-User-ID` is stamped into `reviewer_user_id`, which is precisely what disqualifies that operator from later deciding the appeal."
    PRD 3.3: "Requesting information moves the application `SUBMITTED → INFO_REQUESTED` and raises `info_request_round` by one."
    PRD 3.3: "Supplementing answers an information request and moves the application `INFO_REQUESTED → SUBMITTED`, raising `supplement_count` by one; together with the reviewer's information request this forms the review system's first loop, `SUBMITTED → INFO_REQUESTED → SUBMITTED`, bounded by the two-round budget."
    PRD 3.3: "The reason is recorded on the application, `denied_at` is stamped with the current logical instant, and the course cascades `PENDING_APPROVAL → DENIED` carrying the identical reason text into its own `denial_reason`."

    Design: Corner/rbac/the_reviewer_and_the_panelist_each_take_their_own_step_of_the_approval_chain
    """
    provider = fx.create_probationary_provider(
        name="Riverbend Continuing Education", provider_type="COMMERCIAL"
    )
    course = fx.create_self_certified_course(
        provider,
        title="Trial Advocacy Workshop",
        delivery_format="LIVE_IN_PERSON",
        total_minutes=180,
        presented_at="2026-06-01T09:00:00Z",
        attendance_verification_method="CERTIFICATE",
        credit_allocations=[f.credit_allocation_entry("GENERAL", 180)],
    )
    assert course["status"] == "PENDING_APPROVAL"

    filed = validate_success(
        api.create_course_application(
            course["id"], make_provider_admin_headers(provider["id"])
        ),
        expected_status=201,
    )
    assert filed["status"] == "SUBMITTED"
    assert filed["applicant_role"] == "PROVIDER_ADMIN"
    assert filed["applicant_user_id"] == provider["id"]
    assert filed["info_request_round"] == 0
    assert filed["supplement_count"] == 0
    assert filed["remand_count"] == 0

    asked = validate_success(
        api.application_review_action(
            filed["id"],
            f.review_action_payload("REQUEST_INFO"),
            make_reviewer_headers(REVIEWER_ID),
        ),
        expected_status=200,
    )
    assert asked["status"] == "INFO_REQUESTED"
    assert asked["info_request_round"] == 1
    assert asked["reviewer_user_id"] == REVIEWER_ID

    answered = validate_success(
        api.application_appellant_action(
            filed["id"],
            f.appellant_action_payload("SUPPLEMENT"),
            make_provider_admin_headers(provider["id"]),
        ),
        expected_status=200,
    )
    assert answered["status"] == "SUBMITTED"
    assert answered["supplement_count"] == 1
    assert answered["info_request_round"] == 1

    reason = "The outline devotes no time to substantive legal instruction."
    denied = validate_success(
        api.application_review_action(
            filed["id"],
            f.review_action_payload("DENY", denial_reason=reason),
            make_reviewer_headers(REVIEWER_ID),
        ),
        expected_status=200,
    )
    assert denied["status"] == "DENIED"
    assert denied["reviewer_user_id"] == REVIEWER_ID
    assert denied["denial_reason"] == reason
    assert _same_instant(denied["denied_at"], CLOCK_START)

    denied_course = fx.read_course(course["id"])
    assert denied_course["status"] == "DENIED"
    assert denied_course["denial_reason"] == reason


def test_applicant_appeal_and_panel_grant_close_the_approval_chain(api, board_headers):
    """PRD 2.1: "**`AppealsPanelist`** is an independent panelist who decides appeals of course-approval denials."
    PRD 3.3: "An `AppealsPanelist` decides an `APPEALED` application by naming a `disposition` of `GRANT`, `DENY` or `REMAND`, optionally with a `decision_reason`."
    PRD 3.3: "Appealing contests a denial and moves the application `DENIED → APPEALED`. It requires `appeal_grounds` text, and it must arrive strictly before 30 days have elapsed since `denied_at` as measured on the logical clock — at or after that instant the appeal is `ERR_APPEAL_WINDOW_EXPIRED`. An accepted appeal records the grounds and stamps `appeal_filed_at`."
    PRD 3.3: "All three dispositions record the acting identifier in `appeal_panelist_user_id`."
    PRD 3.3: "`GRANT` moves the application `APPEALED → APPEAL_GRANTED`, stamps `decided_at`, clears the application's `denial_reason` to null, and cascades the course `DENIED → APPROVED` while clearing the course's own `denial_reason` to null."
    PRD 3.2: "It is `PROVIDER_ACCREDITED` when `provider_id` is supplied *and* that sponsor's `self_certification_enabled` is true at the moment of creation; in every other case — no sponsor at all, or a sponsor that is not fully accredited — it is `INDIVIDUAL_APPROVAL`."

    Design: Corner/rbac/the_reviewer_and_the_panelist_each_take_their_own_step_of_the_approval_chain
    """
    provider, course, application = _pending_course_with_application(
        "Riverbend Continuing Education",
        {
            "title": "Trial Advocacy Workshop",
            "delivery_format": "LIVE_IN_PERSON",
            "total_minutes": 180,
            "presented_at": "2026-06-01T09:00:00Z",
            "attendance_verification_method": "CERTIFICATE",
            "credit_allocations": [f.credit_allocation_entry("GENERAL", 180)],
        },
    )
    assert course["approval_pathway"] == "INDIVIDUAL_APPROVAL"

    fx.review_action(
        application["id"], "DENY", REVIEWER_ID,
        denial_reason="The outline devotes no time to substantive legal instruction.",
    )

    grounds = "The syllabus filed with the application answers the reviewer in full."
    appealed = validate_success(
        api.application_appellant_action(
            application["id"],
            f.appellant_action_payload("APPEAL", appeal_grounds=grounds),
            make_provider_admin_headers(provider["id"]),
        ),
        expected_status=200,
    )
    assert appealed["status"] == "APPEALED"
    assert appealed["appeal_grounds"] == grounds
    assert _same_instant(appealed["appeal_filed_at"], CLOCK_START)

    decided = fx.grant_appeal(
        application["id"], PANELIST_ID,
        decision_reason="The panel is satisfied the course carries substantive instruction.",
    )
    assert decided["status"] == "APPEAL_GRANTED"
    assert decided["appeal_panelist_user_id"] == PANELIST_ID
    assert decided["denial_reason"] is None
    assert decided["remand_count"] == 0
    assert _same_instant(decided["decided_at"], CLOCK_START)

    reopened = fx.read_course(course["id"])
    assert reopened["status"] == "APPROVED"
    assert reopened["denial_reason"] is None
    assert reopened["approval_pathway"] == "INDIVIDUAL_APPROVAL"

    rows, meta = validate_paginated(
        api.list_course_applications(course["id"], board_headers)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == application["id"]


BOARD_ONLY_WRITES = [
    "attorney_registration",
    "accreditation_action",
    "compliance_period_creation",
    "reporting_sweep",
    "logical_clock",
    "audit_opening",
]


def _attempt_board_only_write(api, name, provider, attorney):
    """Addresses one of the board's exclusive writes from a role the endpoint
    does not admit, and returns the raw response."""
    if name == "attorney_registration":
        return api.create_attorney(
            f.create_attorney_payload(
                bar_number="RBAC-9001", full_name="Unregistered Applicant"
            ),
            make_provider_admin_headers(provider["id"]),
        )
    if name == "accreditation_action":
        return api.provider_accreditation_action(
            provider["id"],
            f.accreditation_action_payload("GRANT_FULL", provider["version"]),
            make_panelist_headers(PANELIST_ID),
        )
    if name == "compliance_period_creation":
        return api.create_compliance_cycle(
            attorney["id"],
            f.create_compliance_cycle_payload(
                period_start="2026-01-01T00:00:00Z", period_end="2028-01-01T00:00:00Z"
            ),
            make_attorney_headers(attorney["id"]),
        )
    if name == "reporting_sweep":
        return api.create_reporting_sweep(make_reviewer_headers(REVIEWER_ID))
    if name == "logical_clock":
        return api.set_clock("2030-01-01T00:00:00Z", make_panelist_headers(PANELIST_ID))
    if name == "audit_opening":
        return api.create_provider_audit(
            f.create_provider_audit_payload(provider["id"], trigger_type="RANDOM"),
            make_provider_admin_headers(provider["id"]),
        )
    raise AssertionError("unhandled board-only write: " + name)


@pytest.mark.parametrize("write_name", BOARD_ONLY_WRITES)
def test_a_board_only_write_is_refused_to_every_other_role(api, write_name):
    """PRD 2.1: "When the headers are well formed but the named role is not among the roles the addressed endpoint permits, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD 2.8: "**Authorization.** The acting role appears in the endpoint's permitted roles, and where a shared endpoint reserves an action for one role the acting role owns that action — otherwise `ERR_ROLE_NOT_PERMITTED` (403). Applies to every endpoint."

    Design: Corner/rbac/the_four_non_board_roles_cannot_reach_the_boards_exclusive_writes
    """
    provider = fx.create_provider(
        name="Untouched Sponsor Applicant", provider_type="GOVERNMENT"
    )
    attorney = fx.create_attorney(
        bar_number="RBAC-9000", full_name="Perpetua Nkemdirim"
    )

    validate_error(
        _attempt_board_only_write(api, write_name, provider, attorney),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
    )


def test_a_board_only_write_against_a_missing_record_still_answers_the_role_error(api):
    """PRD 2.8: "When a single request violates several rules, the response must name the violation that comes first in the following order. This order is normative: it is what makes an error response predictable, and it is why, for example, a request from an unauthorized role against a non-existent resource returns a permission error rather than a not-found error."

    Design: Corner/rbac/the_four_non_board_roles_cannot_reach_the_boards_exclusive_writes
    """
    validate_error(
        api.attorney_status_change(
            MISSING_ATTORNEY_ID,
            f.status_change_payload("INACTIVE", reason="Retired from practice."),
            make_attorney_headers(MISSING_ATTORNEY_ID),
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
    )


def test_refused_board_only_writes_leave_the_register_untouched(api, board_headers):
    """PRD 2.1: "When the headers are well formed but the named role is not among the roles the addressed endpoint permits, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD 2.4: "Before the clock is ever set it reads exactly `2026-08-01T00:00:00Z`. That fixed startup default is the system's earliest instant and must never fall back to real wall-clock time."
    PRD 3.1: "It stamps the same two-year term into `accreditation_term_start` and `accreditation_term_end`, leaves `self_certification_enabled` false, raises the same `PROVIDER_ANNUAL` assessment for `annual_fee_cents`, and re-scores the sponsor under `REVIEWED_WEIGHTING`."

    Design: Corner/rbac/the_four_non_board_roles_cannot_reach_the_boards_exclusive_writes
    """
    provider = fx.create_provider(
        name="Untouched Sponsor Applicant", provider_type="GOVERNMENT"
    )
    attorney = fx.create_attorney(
        bar_number="RBAC-9000", full_name="Perpetua Nkemdirim"
    )

    for write_name in BOARD_ONLY_WRITES:
        validate_error(
            _attempt_board_only_write(api, write_name, provider, attorney),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        )

    _, cycle_meta = validate_paginated(
        api.list_compliance_cycles(board_headers, params={"attorney_id": attorney["id"]})
    )
    assert cycle_meta["total_count"] == 0

    _, audit_meta = validate_paginated(
        api.list_provider_audits(board_headers, params={"provider_id": provider["id"]})
    )
    assert audit_meta["total_count"] == 0

    untouched = fx.read_provider(provider["id"])
    assert untouched["accreditation_status"] == "APPLIED"
    assert untouched["version"] == 1

    granted = validate_success(
        api.provider_accreditation_action(
            provider["id"],
            f.accreditation_action_payload("GRANT_PROBATIONARY", untouched["version"]),
            board_headers,
        ),
        expected_status=200,
    )
    assert granted["accreditation_status"] == "PROBATIONARY"
    assert granted["self_certification_enabled"] is False
    assert granted["risk_score_variant"] == "REVIEWED_WEIGHTING"
    assert granted["version"] == 2
    assert _same_instant(granted["accreditation_term_start"], CLOCK_START)
    assert _same_instant(granted["accreditation_term_end"], TERM_END_FROM_START)


WEBCAST_COURSE = {
    "title": "Remote Deposition Practice",
    "delivery_format": "LIVE_WEBCAST",
    "total_minutes": 240,
    "presented_at": "2026-06-05T13:00:00Z",
    "attendance_verification_method": "CERTIFICATE",
    "credit_allocations": [{"category": "GENERAL", "minutes": 240}],
}


def test_the_reviewer_and_the_panelist_seats_cannot_be_swapped(api):
    """PRD 2.1: "**`AppealsPanelist`** is an independent panelist who decides appeals of course-approval denials. A panelist cannot file, review or supplement an application — only decide one that is under appeal, and only if that panelist did not review it."
    PRD 2.1: "When the headers are well formed but the named role is not among the roles the addressed endpoint permits, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD 2.8: "When a single request violates several rules, the response must name the violation that comes first in the following order. This order is normative: it is what makes an error response predictable, and it is why, for example, a request from an unauthorized role against a non-existent resource returns a permission error rather than a not-found error."

    Design: Corner/rbac/the_reviewer_cannot_decide_an_appeal_and_the_panelist_cannot_review_or_supplement_one
    """
    reason = "The agenda is a marketing presentation rather than legal instruction."
    provider, course, application = _appealed_application(
        "Cascadia Legal Seminars", reason, dict(WEBCAST_COURSE)
    )
    assert application["status"] == "APPEALED"

    validate_error(
        api.application_appeal_decision(
            application["id"],
            f.appeal_decision_payload("REMAND"),
            make_reviewer_headers(REVIEWER_ID),
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.application_review_action(
            application["id"],
            f.review_action_payload("APPROVE"),
            make_panelist_headers(PANELIST_ID),
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.application_appellant_action(
            application["id"],
            f.appellant_action_payload("SUPPLEMENT"),
            make_panelist_headers(PANELIST_ID),
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
    )

    intact = fx.read_application(application["id"])
    assert intact["status"] == "APPEALED"
    assert intact["reviewer_user_id"] == REVIEWER_ID
    assert intact["appeal_panelist_user_id"] is None
    assert intact["decided_at"] is None
    assert intact["supplement_count"] == 0
    assert intact["info_request_round"] == 0
    assert fx.read_course(course["id"])["status"] == "DENIED"


def test_a_panelist_who_never_reviewed_the_application_may_deny_the_appeal(api):
    """PRD 3.3: "An `AppealsPanelist` decides an `APPEALED` application by naming a `disposition` of `GRANT`, `DENY` or `REMAND`, optionally with a `decision_reason`."
    PRD 3.3: "All three dispositions record the acting identifier in `appeal_panelist_user_id`."
    PRD 3.3: "`DENY` moves the application `APPEALED → APPEAL_DENIED`, stamps `decided_at`, records the supplied reason in `denial_reason`, and leaves the course sitting in `DENIED`; this closes the matter for that application, and a fresh application becomes possible only once the course itself is re-created."

    Design: Corner/rbac/the_reviewer_cannot_decide_an_appeal_and_the_panelist_cannot_review_or_supplement_one
    """
    reason = "The agenda is a marketing presentation rather than legal instruction."
    provider, course, application = _appealed_application(
        "Cascadia Legal Seminars", reason, dict(WEBCAST_COURSE)
    )

    panel_reason = "The panel agrees the agenda carries no substantive instruction."
    decided = fx.deny_appeal(
        application["id"], PANELIST_ID, decision_reason=panel_reason
    )
    assert decided["status"] == "APPEAL_DENIED"
    assert decided["appeal_panelist_user_id"] == PANELIST_ID
    assert decided["denial_reason"] == panel_reason
    assert decided["remand_count"] == 0
    assert _same_instant(decided["decided_at"], CLOCK_START)

    left_denied = fx.read_course(course["id"])
    assert left_denied["status"] == "DENIED"
    assert left_denied["denial_reason"] == reason


ATTORNEY_OR_PROVIDER_ONLY_WRITES = [
    "credit_record_by_the_board",
    "affirmation_by_a_provider",
    "certification_by_the_board",
    "reciprocity_claim_by_a_provider",
    "session_roster_by_an_attorney",
]


def _approved_course_and_open_period():
    """An accredited sponsor with one approved live course, plus one attorney
    whose compliance period covers that course's session.
    Returns (provider, course, attorney, cycle)."""
    provider = fx.create_accredited_provider(
        name="Meridian Bar Academy", provider_type="BAR_ASSOCIATION"
    )
    course = fx.create_self_certified_course(
        provider,
        title="Depositions From Start To Finish",
        delivery_format="LIVE_IN_PERSON",
        total_minutes=300,
        presented_at="2026-06-15T09:00:00Z",
        attendance_verification_method="CERTIFICATE",
        credit_allocations=[f.credit_allocation_entry("GENERAL", 300)],
    )
    attorney = fx.create_attorney(
        bar_number="RBAC-2001",
        full_name="Anselm Karagiannis",
        admission_date="2005-03-01T00:00:00Z",
    )
    cycle = fx.create_cycle(
        attorney["id"], "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z"
    )
    return provider, course, attorney, cycle


def _attempt_entity_role_write(api, name, provider, course, attorney, cycle):
    """Addresses one of the two entity-backed roles' exclusive writes from a seat
    the endpoint does not admit, and returns the raw response."""
    if name == "credit_record_by_the_board":
        return api.create_credit_record(
            f.create_credit_record_payload(
                attorney["id"], course["id"],
                verification_method="CERTIFICATE",
                attended_minutes=300,
                completion_date="2026-06-15T09:00:00Z",
            ),
            BOARD,
        )
    if name == "affirmation_by_a_provider":
        return api.create_affirmation(
            cycle["id"],
            f.create_affirmation_payload("SELF_STUDY_AFFIRMATION"),
            make_provider_admin_headers(provider["id"]),
        )
    if name == "certification_by_the_board":
        return api.certify_cycle(cycle["id"], f.certification_payload(), BOARD)
    if name == "reciprocity_claim_by_a_provider":
        return api.create_reciprocity_claim(
            f.create_reciprocity_claim_payload(attorney["id"], attorney["version"]),
            make_provider_admin_headers(provider["id"]),
        )
    if name == "session_roster_by_an_attorney":
        return api.create_attendance_report(
            f.create_attendance_report_payload(
                course["id"], "2026-06-15",
                [f.roster_entry(attorney["bar_number"], 300)],
            ),
            make_attorney_headers(attorney["id"]),
        )
    raise AssertionError("unhandled entity-role write: " + name)


@pytest.mark.parametrize("write_name", ATTORNEY_OR_PROVIDER_ONLY_WRITES)
def test_an_entity_role_exclusive_write_is_refused_to_every_other_role(api, write_name):
    """PRD 2.1: "**`ProviderAdmin`** administers exactly one provider. It registers courses under its own sponsorship, files applications and session rosters, and settles its own provider-side fees."
    PRD 2.1: "**`Attorney`** is a licensed attorney subject to the requirement. An attorney claims credit, files affirmations, certifies its own compliance periods, files reciprocity and comity claims and complaints, and may seek individual approval of a course that has no sponsoring provider."
    PRD 2.1: "When the headers are well formed but the named role is not among the roles the addressed endpoint permits, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/the_attorney_and_provider_exclusive_writes_cannot_be_swapped_or_taken_by_the_board
    """
    provider, course, attorney, cycle = _approved_course_and_open_period()

    validate_error(
        _attempt_entity_role_write(api, write_name, provider, course, attorney, cycle),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
    )


def test_the_attorneys_own_credit_filing_lands_where_the_boards_was_refused(api, board_headers):
    """PRD 2.1: "When the headers are well formed but the named role is not among the roles the addressed endpoint permits, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD 3.5: "With `CERTIFICATE` or `AFFIRMATION`, the record is created in `PENDING_VERIFICATION` and waits: a certificate claim waits for board adjudication, an affirmation claim waits for the attorney's own sworn affirmation."
    PRD 3.5: "A `LIVE_IN_PERSON` course always yields `LIVE`."
    PRD 3.6: "While a cycle's `credit_status` is `OPEN`, the provisional result is what gets persisted into the cycle's `earned_*` fields and into each record's `countable_minutes`."

    Design: Corner/rbac/the_attorney_and_provider_exclusive_writes_cannot_be_swapped_or_taken_by_the_board
    """
    provider, course, attorney, cycle = _approved_course_and_open_period()

    for write_name in ATTORNEY_OR_PROVIDER_ONLY_WRITES:
        validate_error(
            _attempt_entity_role_write(
                api, write_name, provider, course, attorney, cycle
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        )

    _, affirmation_meta = validate_paginated(
        api.list_affirmations(cycle["id"], board_headers)
    )
    assert affirmation_meta["total_count"] == 0

    _, roster_meta = validate_paginated(
        api.list_course_attendance_reports(course["id"], board_headers)
    )
    assert roster_meta["total_count"] == 0

    _, claim_meta = validate_paginated(
        api.list_attorney_reciprocity_claims(attorney["id"], board_headers)
    )
    assert claim_meta["total_count"] == 0

    unmoved_cycle = fx.read_cycle(cycle["id"])
    assert unmoved_cycle["credit_status"] == "OPEN"
    assert unmoved_cycle["certified_at"] is None
    assert unmoved_cycle["carryover_out_general_minutes"] == 0
    assert unmoved_cycle["carryover_out_ethics_minutes"] == 0
    assert fx.read_attorney(attorney["id"])["version"] == attorney["version"]

    filed = validate_success(
        api.create_credit_record(
            f.create_credit_record_payload(
                attorney["id"], course["id"],
                verification_method="CERTIFICATE",
                attended_minutes=300,
                completion_date="2026-06-15T09:00:00Z",
            ),
            make_attorney_headers(attorney["id"]),
        ),
        expected_status=201,
    )
    assert filed["status"] == "PENDING_VERIFICATION"
    assert filed["credited_general_minutes"] == 300
    assert filed["effective_format"] == "LIVE"
    assert filed["cycle_id"] == cycle["id"]

    counted = fx.read_cycle(cycle["id"])
    assert counted["earned_countable_minutes"] == 300

    rows, record_meta = validate_paginated(
        api.list_credit_records(board_headers, params={"attorney_id": attorney["id"]})
    )
    assert record_meta["total_count"] == 1
    assert rows[0]["id"] == filed["id"]


def _appealed_after_one_information_round():
    """A denied and appealed application that already spent one information round,
    denied by REVIEWER_ID. Returns (provider, course, application, denial_reason)."""
    provider, course, application = _pending_course_with_application(
        "Northgate Technology CLE",
        {
            "title": "Practice Management Software In Depth",
            "delivery_format": "LIVE_WEBCAST",
            "total_minutes": 120,
            "presented_at": "2026-06-20T15:00:00Z",
            "attendance_verification_method": "ATTENDANCE_CODE",
            "credit_allocations": [f.credit_allocation_entry("TECHNOLOGY", 120)],
        },
    )
    fx.review_action(application["id"], "REQUEST_INFO", REVIEWER_ID)
    reason = "The submitted outline still omits the promised technology content."
    fx.review_action(application["id"], "DENY", REVIEWER_ID, denial_reason=reason)
    application = fx.appellant_action(
        application["id"], "APPEAL",
        make_provider_admin_headers(provider["id"]),
        appeal_grounds="The full outline was filed with the original application.",
    )
    return provider, course, application, reason


def test_the_reviewer_who_denied_the_application_may_not_decide_its_appeal(api):
    """PRD 2.1: "The operator who issued a review action on an application (recorded as `reviewer_user_id`) may not decide that application's appeal, and the operator who filed a complaint (recorded as `complainant_user_id`) may not substantiate or dismiss it. Either violation is `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD 3.3: "Every disposition requires the application to be in `APPEALED` and requires the acting `X-User-ID` to differ from `reviewer_user_id`; a panelist who previously reviewed the application is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/the_reviewer_who_denied_an_application_cannot_decide_its_appeal
    """
    provider, course, application, reason = _appealed_after_one_information_round()
    assert application["status"] == "APPEALED"
    assert application["reviewer_user_id"] == REVIEWER_ID

    validate_error(
        api.application_appeal_decision(
            application["id"],
            f.appeal_decision_payload(
                "REMAND", decision_reason="The matter deserves a second look."
            ),
            make_panelist_headers(REVIEWER_ID),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )

    intact = fx.read_application(application["id"])
    assert intact["status"] == "APPEALED"
    assert intact["reviewer_user_id"] == REVIEWER_ID
    assert intact["appeal_panelist_user_id"] is None
    assert intact["remand_count"] == 0
    assert intact["denial_reason"] == reason
    assert fx.read_course(course["id"])["status"] == "DENIED"


def test_an_unconflicted_panelist_remands_and_clears_the_reviewers_stamp(api):
    """PRD 3.3: "All three dispositions record the acting identifier in `appeal_panelist_user_id`."
    PRD 3.3: "`REMAND` moves the application `APPEALED → SUBMITTED` and sends the whole matter back for re-review: it raises `remand_count` by one, clears `reviewer_user_id`, `denial_reason` and `denied_at` back to null, resets `info_request_round` to 0 so the application re-enters review with a fresh two-round information budget, and cascades the course `DENIED → PENDING_APPROVAL` with the course's `denial_reason` cleared."

    Design: Corner/rbac/the_reviewer_who_denied_an_application_cannot_decide_its_appeal
    """
    provider, course, application, reason = _appealed_after_one_information_round()
    assert application["info_request_round"] == 1

    remanded = validate_success(
        api.application_appeal_decision(
            application["id"],
            f.appeal_decision_payload(
                "REMAND", decision_reason="The panel returns the matter for re-review."
            ),
            make_panelist_headers(PANELIST_ID),
        ),
        expected_status=200,
    )
    assert remanded["status"] == "SUBMITTED"
    assert remanded["remand_count"] == 1
    assert remanded["appeal_panelist_user_id"] == PANELIST_ID
    assert remanded["reviewer_user_id"] is None
    assert remanded["denial_reason"] is None
    assert remanded["denied_at"] is None
    assert remanded["info_request_round"] == 0

    reopened = fx.read_course(course["id"])
    assert reopened["status"] == "PENDING_APPROVAL"
    assert reopened["denial_reason"] is None


PEER_WRITES = [
    "course_under_a_peers_sponsorship",
    "application_on_a_peers_course",
    "appellant_action_on_a_peers_application",
    "certification_of_a_peers_period",
    "reciprocity_claim_naming_a_peer",
]


def _two_sponsors_and_two_attorneys():
    """Two sponsors, each with a course of its own, and two attorneys, the first
    of which holds an open compliance period.
    Returns (sponsor_one, approved_course, sponsor_two, pending_course,
    application, attorney_one, period_one, attorney_two)."""
    sponsor_one = fx.create_accredited_provider(
        name="Lakeshore Bar Association CLE", provider_type="BAR_ASSOCIATION"
    )
    approved_course = fx.create_self_certified_course(
        sponsor_one,
        title="Fiduciary Duties On Demand",
        delivery_format="ON_DEMAND",
        total_minutes=180,
        presented_at="2026-05-01T09:00:00Z",
        attendance_verification_method="ROSTER",
        credit_allocations=[f.credit_allocation_entry("GENERAL", 180)],
    )
    sponsor_two = fx.create_probationary_provider(
        name="Summit Legal Training", provider_type="COMMERCIAL"
    )
    pending_course = fx.create_self_certified_course(
        sponsor_two,
        title="Advanced Motions Practice",
        delivery_format="ON_DEMAND",
        total_minutes=180,
        presented_at="2026-05-10T09:00:00Z",
        attendance_verification_method="CERTIFICATE",
        credit_allocations=[f.credit_allocation_entry("GENERAL", 180)],
    )
    application = fx.submit_application(
        pending_course["id"], make_provider_admin_headers(sponsor_two["id"])
    )
    attorney_one = fx.create_attorney(
        bar_number="RBAC-3001",
        full_name="Ottoline Fairweather",
        admission_date="2004-07-07T00:00:00Z",
    )
    period_one = fx.create_cycle(
        attorney_one["id"], "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z"
    )
    attorney_two = fx.create_attorney(
        bar_number="RBAC-3002",
        full_name="Barnabas Quintrell",
        admission_date="2006-02-02T00:00:00Z",
    )
    return (sponsor_one, approved_course, sponsor_two, pending_course, application,
            attorney_one, period_one, attorney_two)


def _attempt_peer_write(api, name, register):
    """Addresses a resource belonging to a same-role peer, and returns the raw
    response."""
    (sponsor_one, approved_course, sponsor_two, pending_course, application,
     attorney_one, period_one, attorney_two) = register
    if name == "course_under_a_peers_sponsorship":
        return api.create_course(
            f.create_course_payload(
                provider_id=sponsor_one["id"],
                title="Borrowed Sponsorship Seminar",
                delivery_format="ON_DEMAND",
                total_minutes=180,
                presented_at="2026-05-20T09:00:00Z",
                attendance_verification_method="CERTIFICATE",
                credit_allocations=[f.credit_allocation_entry("GENERAL", 180)],
            ),
            make_provider_admin_headers(sponsor_two["id"]),
        )
    if name == "application_on_a_peers_course":
        return api.create_course_application(
            pending_course["id"], make_provider_admin_headers(sponsor_one["id"])
        )
    if name == "appellant_action_on_a_peers_application":
        return api.application_appellant_action(
            application["id"],
            f.appellant_action_payload("SUPPLEMENT"),
            make_provider_admin_headers(sponsor_one["id"]),
        )
    if name == "certification_of_a_peers_period":
        return api.certify_cycle(
            period_one["id"],
            f.certification_payload(),
            make_attorney_headers(attorney_two["id"]),
        )
    if name == "reciprocity_claim_naming_a_peer":
        return api.create_reciprocity_claim(
            f.create_reciprocity_claim_payload(
                attorney_one["id"], attorney_one["version"]
            ),
            make_attorney_headers(attorney_two["id"]),
        )
    raise AssertionError("unhandled peer write: " + name)


@pytest.mark.parametrize("write_name", PEER_WRITES)
def test_a_peer_of_the_same_role_is_refused_as_a_non_owner(api, write_name):
    """PRD 2.1: "An entity-backed role addressing a resource it does not own is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403); the same code covers a supplement or an appeal attempted by anyone other than the application's own `applicant_user_id`."
    PRD 3.2: "A `ProviderAdmin` registers a course under its own sponsorship and must supply a `provider_id` equal to its own `X-User-ID`; supplying anyone else's is `ERR_NOT_RESOURCE_OWNER`."
    PRD 3.8: "Certification is the attorney's own act: a sworn declaration that the period is complete, filed by the attorney against one of its own cycles."
    PRD 3.7: "A claim is filed by the attorney themselves and names `attorney_id` (which must equal the acting `X-User-ID`), the `basis`, the two-letter `origin_jurisdiction` that accredited the instruction, the `origin_course_title` (1 to 200 characters), the `origin_credit_hours` as awarded there, the `origin_category` label used there, and the `completion_date`."

    Design: Corner/rbac/a_provider_admin_cannot_reach_another_providers_course_and_an_attorney_cannot_reach_another_attorneys_cycle
    """
    register = _two_sponsors_and_two_attorneys()

    validate_error(
        _attempt_peer_write(api, write_name, register),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
    )


def test_a_peer_sponsor_cannot_file_a_roster_against_another_sponsors_course(api, board_headers):
    """PRD 2.1: "When `X-User-Role` is `ProviderAdmin`, `X-User-ID` is the `id` of the acting `Provider`; ownership checks on any resource that references a provider compare the resource's provider reference to `X-User-ID` — a course's or an audit's `provider_id`, and for a session roster the `provider_id` of the roster's course."
    PRD 3.5: "The roster's course must belong to the acting provider; someone else's course is `ERR_COURSE_PROVIDER_MISMATCH`."

    Design: Corner/rbac/a_provider_admin_cannot_reach_another_providers_course_and_an_attorney_cannot_reach_another_attorneys_cycle
    """
    register = _two_sponsors_and_two_attorneys()
    (sponsor_one, approved_course, sponsor_two, _pending, _application,
     attorney_one, _period, _attorney_two) = register

    validate_error_is_one_of(
        api.create_attendance_report(
            f.create_attendance_report_payload(
                approved_course["id"], "2026-07-01",
                [f.roster_entry(attorney_one["bar_number"], 180)],
            ),
            make_provider_admin_headers(sponsor_two["id"]),
        ),
        [ApiErrorId.ERR_NOT_RESOURCE_OWNER, ApiErrorId.ERR_COURSE_PROVIDER_MISMATCH],
    )

    _, roster_meta = validate_paginated(
        api.list_course_attendance_reports(approved_course["id"], board_headers)
    )
    assert roster_meta["total_count"] == 0


def test_ownership_refusals_write_nothing_and_the_owner_still_registers_its_own_course(api, board_headers):
    """PRD 2.1: "An entity-backed role addressing a resource it does not own is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403); the same code covers a supplement or an appeal attempted by anyone other than the application's own `applicant_user_id`."
    PRD 3.2: "A `ProviderAdmin` registers a course under its own sponsorship and must supply a `provider_id` equal to its own `X-User-ID`; supplying anyone else's is `ERR_NOT_RESOURCE_OWNER`."
    PRD 3.2: "Every other course is created in `PENDING_APPROVAL` and stays there until an application is decided; if it names a sponsor, only that sponsor's `courses_total_count` rises."

    Design: Corner/rbac/a_provider_admin_cannot_reach_another_providers_course_and_an_attorney_cannot_reach_another_attorneys_cycle
    """
    register = _two_sponsors_and_two_attorneys()
    (sponsor_one, approved_course, sponsor_two, pending_course, application,
     attorney_one, period_one, attorney_two) = register

    for write_name in PEER_WRITES:
        validate_error(
            _attempt_peer_write(api, write_name, register),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        )

    _, sponsor_one_courses = validate_paginated(
        api.list_courses(board_headers, params={"provider_id": sponsor_one["id"]})
    )
    assert sponsor_one_courses["total_count"] == 1

    _, claim_meta = validate_paginated(
        api.list_attorney_reciprocity_claims(attorney_one["id"], board_headers)
    )
    assert claim_meta["total_count"] == 0

    unmoved_period = fx.read_cycle(period_one["id"])
    assert unmoved_period["credit_status"] == "OPEN"
    assert unmoved_period["certified_at"] is None

    unmoved_application = fx.read_application(application["id"])
    assert unmoved_application["status"] == "SUBMITTED"
    assert unmoved_application["supplement_count"] == 0

    own_course = validate_success(
        api.create_course(
            f.create_course_payload(
                provider_id=sponsor_two["id"],
                title="Summit Motions Practice Refresher",
                delivery_format="ON_DEMAND",
                total_minutes=180,
                presented_at="2026-05-25T09:00:00Z",
                attendance_verification_method="CERTIFICATE",
                credit_allocations=[f.credit_allocation_entry("GENERAL", 180)],
            ),
            make_provider_admin_headers(sponsor_two["id"]),
        ),
        expected_status=201,
    )
    assert own_course["provider_id"] == sponsor_two["id"]
    assert own_course["status"] == "PENDING_APPROVAL"

    _, sponsor_two_courses = validate_paginated(
        api.list_courses(board_headers, params={"provider_id": sponsor_two["id"]})
    )
    assert sponsor_two_courses["total_count"] == 2


def _two_sponsors_with_annual_assessments(api, board_headers):
    """Two sponsors whose grants each raised one provider-side annual assessment,
    one at a supplied fee and one at the board's standard fee, plus one attorney
    who owes nothing. Returns (sponsor_one, fee_one, sponsor_two, fee_two, attorney)."""
    sponsor_one = fx.create_probationary_provider(
        name="Ridgeline Commercial CLE", provider_type="COMMERCIAL", annual_fee_cents=80000
    )
    sponsor_two = fx.create_accredited_provider(
        name="Harbor County Bar Association", provider_type="BAR_ASSOCIATION"
    )
    attorney = fx.create_attorney(
        bar_number="RBAC-4001",
        full_name="Cordelia Ashgrove",
        admission_date="2008-08-08T00:00:00Z",
    )

    rows_one, _ = validate_paginated(
        api.list_fee_assessments(
            board_headers,
            params={"provider_id": sponsor_one["id"], "fee_type": "PROVIDER_ANNUAL"},
        )
    )
    rows_two, _ = validate_paginated(
        api.list_fee_assessments(
            board_headers,
            params={"provider_id": sponsor_two["id"], "fee_type": "PROVIDER_ANNUAL"},
        )
    )
    assert len(rows_one) == 1
    assert len(rows_two) == 1
    return sponsor_one, rows_one[0], sponsor_two, rows_two[0], attorney


@pytest.mark.parametrize("waiver_seat", ["attorney", "provider_admin"])
def test_only_the_board_may_request_a_waiver_on_a_shared_settlement_endpoint(api, board_headers, waiver_seat):
    """PRD 2.1: "The same code covers action-level reservations on shared endpoints: fee settlement is open to three roles, but only a `BoardAdmin` may request the `WAIVE` action there, so a `WAIVE` from an `Attorney` or a `ProviderAdmin` is an `ERR_ROLE_NOT_PERMITTED`."
    PRD 3.9: "`WAIVE` is reserved to the board alone and requires a `waiver_reason`; an attorney or a provider administrator requesting a waiver is rejected with `ERR_ROLE_NOT_PERMITTED` even though the endpoint itself admits their role."
    PRD 3.1: "An `annual_fee_cents` figure may be supplied and must be zero or greater; when it is omitted the board's standard annual accreditation fee of 120000 cents — twelve hundred dollars — is used."

    Design: Corner/rbac/waiving_an_assessment_is_reserved_to_the_board_while_paying_is_shared
    """
    sponsor_one, fee_one, sponsor_two, fee_two, attorney = (
        _two_sponsors_with_annual_assessments(api, board_headers)
    )
    assert fee_one["amount_cents"] == 80000
    assert fee_two["amount_cents"] == 120000
    assert fee_one["attorney_id"] is None
    assert fee_one["provider_id"] == sponsor_one["id"]

    seats = {
        "attorney": make_attorney_headers(attorney["id"]),
        "provider_admin": make_provider_admin_headers(sponsor_one["id"]),
    }
    validate_error(
        api.fee_settlement(
            fee_one["id"],
            f.settlement_payload("WAIVE", waiver_reason="The sponsor asks for relief."),
            seats[waiver_seat],
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
    )

    untouched = fx.read_fee_assessment(fee_one["id"])
    assert untouched["status"] == "ASSESSED"
    assert untouched["settled_at"] is None
    assert untouched["waiver_reason"] is None


def test_the_board_waives_while_the_sponsor_pays_and_no_attorney_balance_moves(api, board_headers):
    """PRD 3.9: "Either action stamps `settled_at` with the current instant, moves `status` to `PAID` or `WAIVED` accordingly, and — when the assessment names an `attorney_id` — lowers that attorney's `outstanding_fee_cents` by exactly this assessment's `amount_cents`. A provider-side assessment, whose `attorney_id` is null and whose `provider_id` is set, moves no attorney balance."
    PRD 2.11: "An assessment carries `amount_cents`, an `assessed_at` instant, a `status` of `ASSESSED`, `PAID`, `WAIVED` or `VOIDED` starting at `ASSESSED`, a `settled_at` instant recorded when it leaves `ASSESSED`, and a `waiver_reason` recorded only when it is waived."
    PRD 2.1: "**`ProviderAdmin`** administers exactly one provider. It registers courses under its own sponsorship, files applications and session rosters, and settles its own provider-side fees."

    Design: Corner/rbac/waiving_an_assessment_is_reserved_to_the_board_while_paying_is_shared
    """
    sponsor_one, fee_one, sponsor_two, fee_two, attorney = (
        _two_sponsors_with_annual_assessments(api, board_headers)
    )

    reason = "The board waives the fee for a first-year commercial sponsor."
    waived = validate_success(
        api.fee_settlement(
            fee_one["id"],
            f.settlement_payload("WAIVE", waiver_reason=reason),
            board_headers,
        ),
        expected_status=200,
    )
    assert waived["status"] == "WAIVED"
    assert waived["waiver_reason"] == reason
    assert _same_instant(waived["settled_at"], CLOCK_START)

    paid = validate_success(
        api.fee_settlement(
            fee_two["id"],
            f.settlement_payload("PAY"),
            make_provider_admin_headers(sponsor_two["id"]),
        ),
        expected_status=200,
    )
    assert paid["status"] == "PAID"
    assert paid["waiver_reason"] is None
    assert _same_instant(paid["settled_at"], CLOCK_START)

    assert fx.read_attorney(attorney["id"])["outstanding_fee_cents"] == 0

    _, still_assessed = validate_paginated(
        api.list_fee_assessments(board_headers, params={"status": "ASSESSED"})
    )
    assert still_assessed["total_count"] == 0
