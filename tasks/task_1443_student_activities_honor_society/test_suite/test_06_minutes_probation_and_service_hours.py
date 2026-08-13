"""Meeting minutes ratification loop, probation case branching, service-hour
entry field rules and terminal lockdown, and member-role denial."""
from test_helpers import (
    ApiErrorId,
    add_member,
    api_client,
    assert_minutes,
    assert_probation_case,
    create_active_chapter,
    create_probation_case_payload,
    create_service_entry_payload,
    draft_minutes,
    elect_officer,
    make_member_headers,
    make_officer_headers,
    open_probation_case,
    resolve_probation_case,
    set_clock,
    setup_cycle_in_review,
    setup_secretary_with_minutes,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADVISOR = TEST_USERS["advisor_headers"]
ADVISOR_ID = "adv-1"


def _officer(member):
    return make_officer_headers(member["id"])


class TestMeetingMinutesCycle:
    def test_approved_minutes_amend_cycles_back_to_submitted_and_reapproved(self):
        """PRD section 3.4: "Approval is not the end of the road: a secretary
        may amend approved minutes, provided the new `notes` differ from the
        prior body, and amendment moves the minutes from `APPROVED` to
        `AMENDED` — from which the system immediately returns them to
        `SUBMITTED` once the amended body is saved, cycling them back through
        advisor approval."
        PRD section 3.4: "The advisor then approves submitted minutes, moving
        them to `APPROVED` and recording themselves in `approved_by_user_id`."

        Design: Difficulty/non_linear_state_machine/meeting_minutes_approved_amended_resubmitted_cycle
        """
        env = setup_secretary_with_minutes()
        ch_id = env["chapter"]["id"]
        minutes = env["minutes"]
        secretary = env["officer_member"]

        submitted = validate_success(api_client.submit_minutes(
            ch_id, minutes["id"], _officer(secretary)))
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_by_officer_id"] == env["role"]["id"]

        approved = validate_success(api_client.approve_minutes(
            ch_id, minutes["id"], ADVISOR))
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == ADVISOR_ID

        amended = validate_success(api_client.amend_minutes(
            ch_id, minutes["id"], {"notes": "Amended v2 with corrections"},
            _officer(secretary)))
        assert_minutes(amended)
        # AMENDED is transient: the system returns the minutes to SUBMITTED
        # once the amended body is saved.
        after_amend = validate_success(api_client.get_minutes(
            ch_id, minutes["id"], ADVISOR))
        assert after_amend["status"] == "SUBMITTED"
        assert after_amend["notes"] == "Amended v2 with corrections"

        reapproved = validate_success(api_client.approve_minutes(
            ch_id, minutes["id"], ADVISOR))
        assert reapproved["status"] == "APPROVED"
        assert reapproved["notes"] == "Amended v2 with corrections"

    def test_non_secretary_officer_cannot_submit_minutes(self):
        """PRD section 3.4: "Submission is the secretary's exclusive privilege:
        moving minutes from `DRAFT` to `SUBMITTED` requires the caller to hold
        an `ACTIVE` officer role whose `office` is `SECRETARY` — any other
        caller is rejected with `ERR_NOT_AN_OFFICER` — and the officer recorded
        in `called_by_officer_id` must still hold an `ACTIVE` role, a lapse
        surfacing as `ERR_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/meeting_minutes_approved_amended_resubmitted_cycle
        """
        env = setup_cycle_in_review(member_overrides=[{}, {}])
        ch_id, cy_id = env["chapter"]["id"], env["cycle"]["id"]
        secretary, president = env["members"]
        _el1, _sec_role = elect_officer(ch_id, cy_id, "SECRETARY",
                                        secretary["id"])
        _el2, pres_role = elect_officer(ch_id, cy_id, "PRESIDENT",
                                        president["id"])
        minutes = draft_minutes(ch_id, pres_role, president)
        resp = api_client.submit_minutes(ch_id, minutes["id"],
                                         _officer(president))
        validate_error(resp, ApiErrorId.ERR_NOT_AN_OFFICER)


class TestProbationCaseBranching:
    def test_open_appealed_resolved_path(self):
        """PRD section 3.7: "A timely appeal moves the case to `APPEALED`."
        PRD section 3.7: "Resolution stamps `resolved_by_user_id`, moves the
        case to `RESOLVED`, and cascades according to the outcome."
        PRD section 3.7: "their `probation_strikes` — the count of their
        `RESOLVED` cases bearing a confirmed outcome — increases by one".

        Design: Difficulty/non_linear_state_machine/probation_case_open_appealed_resolved_cycle
        """
        set_clock()
        chapter = create_active_chapter()
        member = add_member(chapter["id"])
        case = open_probation_case(chapter["id"], member["id"],
                                   reason_code="MISSED_MEETINGS")
        assert case["status"] == "OPEN"
        assert case["opened_at"]

        appealed = validate_success(api_client.appeal_probation_case(
            chapter["id"], member["id"], case["id"],
            make_member_headers(member["id"])))
        assert appealed["status"] == "APPEALED"

        resolved = resolve_probation_case(chapter["id"], member["id"],
                                          case["id"])
        assert_probation_case(resolved)
        assert resolved["status"] == "RESOLVED"
        assert resolved["outcome"] == "STANDARDS_VIOLATION_CONFIRMED"
        assert resolved["resolved_by_user_id"] == ADVISOR_ID

        standing = validate_success(api_client.get_member_standing(
            chapter["id"], member["id"], ADVISOR))
        assert standing["probation_strikes"] == 1

    def test_open_resolved_direct_path(self):
        """PRD section 3.7: "Resolution belongs to the advisor, from either
        `OPEN` or `APPEALED`, and requires an `outcome`."
        PRD section 3.7: "Resolution stamps `resolved_by_user_id`, moves the
        case to `RESOLVED`, and cascades according to the outcome."

        Design: Difficulty/non_linear_state_machine/probation_case_open_appealed_resolved_cycle
        """
        set_clock()
        chapter = create_active_chapter()
        member = add_member(chapter["id"])
        case = open_probation_case(chapter["id"], member["id"])
        resolved = resolve_probation_case(chapter["id"], member["id"],
                                          case["id"])
        assert resolved["status"] == "RESOLVED"
        assert resolved["outcome"] == "STANDARDS_VIOLATION_CONFIRMED"
        assert resolved["resolved_by_user_id"] == ADVISOR_ID
        standing = validate_success(api_client.get_member_standing(
            chapter["id"], member["id"], ADVISOR))
        assert standing["probation_strikes"] == 1


class TestServiceHourEntryRules:
    def test_hours_not_quarter_increment_rejected(self):
        """PRD section 3.3: "Two field rules guard the log at creation: `hours`
        must be greater than zero, no more than 12, and an exact multiple of
        0.25 — anything else is rejected with `ERR_INVALID_SERVICE_HOURS`
        (HTTP 422) — and `service_date` must not lie in the future relative to
        the logical clock, else the log is rejected with
        `ERR_FUTURE_SERVICE_DATE` (HTTP 422)."

        Design: Corner/validations/invalid_service_hours_not_quarter_increment
        """
        set_clock("2026-08-05T00:00:00Z")
        chapter = create_active_chapter()
        member = add_member(chapter["id"])
        resp = api_client.create_service_entry(
            chapter["id"], member["id"],
            create_service_entry_payload(hours=2.3), ADVISOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_SERVICE_HOURS)

    def test_future_service_date_rejected(self):
        """PRD section 3.3: "`service_date` must not lie in the future relative
        to the logical clock, else the log is rejected with
        `ERR_FUTURE_SERVICE_DATE` (HTTP 422)."

        Design: Corner/validations/future_service_date_rejected
        """
        set_clock()
        chapter = create_active_chapter()
        member = add_member(chapter["id"])
        resp = api_client.create_service_entry(
            chapter["id"], member["id"],
            create_service_entry_payload(service_date="2027-01-01T00:00:00Z",
                                         hours=2.0),
            ADVISOR)
        validate_error(resp, ApiErrorId.ERR_FUTURE_SERVICE_DATE)

    def test_rejected_entry_is_terminal(self):
        """PRD section 3.3: "`VERIFIED`, `REJECTED`, and `VOID` are the entry's
        terminal states."
        PRD section 2.6: "then the target resource's state-machine legality
        (`ERR_INVALID_STATE`, HTTP 409, raised whenever a transition is
        attempted from a state that does not permit it)."

        Design: Corner/state_machines/service_hour_entry_terminal_lockdown
        """
        set_clock("2026-08-05T00:00:00Z")
        chapter = create_active_chapter()
        member = add_member(chapter["id"])
        entry = validate_success(api_client.create_service_entry(
            chapter["id"], member["id"], create_service_entry_payload(),
            ADVISOR), expected_status=201)
        assert entry["status"] == "PENDING_VERIFICATION"
        rejected = validate_success(api_client.reject_service_entry(
            chapter["id"], member["id"], entry["id"],
            {"rejection_reason": "No supervisor confirmation"}, ADVISOR))
        assert rejected["status"] == "REJECTED"
        resp = api_client.verify_service_entry(chapter["id"], member["id"],
                                               entry["id"], ADVISOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestMemberRoleDenial:
    def test_member_cannot_open_probation_case(self):
        """PRD section 2.1: "Once authenticated, access to each operation is
        restricted by role per the endpoint catalogue in §4; an authenticated
        caller attempting an operation outside their role is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD section 3.7: "Standards enforcement begins when the advisor opens a
        probation case against a member, supplying their own identity as
        `opened_by_user_id`, a `reason_code` of `GPA_BELOW_THRESHOLD`,
        `SERVICE_HOURS_SHORTFALL`, `CONDUCT_VIOLATION`, or `MISSED_MEETINGS`,
        and the narrative `evidence_text`."

        Design: Corner/rbac/member_cannot_open_probation_case
        """
        set_clock()
        chapter = create_active_chapter()
        member = add_member(chapter["id"])
        resp = api_client.create_probation_case(
            chapter["id"], member["id"],
            create_probation_case_payload(ADVISOR_ID),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
