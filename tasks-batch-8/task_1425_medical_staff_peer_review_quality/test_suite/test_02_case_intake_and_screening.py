"""Case intake, screening decisions, terminal lockdown, listing filters, and
the referral cooldown window."""
from test_helpers import (
    COOLDOWN_DAY_29,
    COOLDOWN_DAY_30,
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_instant_equals,
    create_case,
    create_case_payload,
    create_provider,
    screen_case_in,
    seat_member,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

TEST_QD = TEST_USERS["quality_director_headers"]


class TestCaseCreation:
    def test_case_born_in_referred_status(self, peer_review_coordinator_headers):
        """PRD §3.2: "The case is born in `REFERRED` status."
        PRD §2.4: "`version` (integer): a system-managed integer that
        increments with every modification to the resource."

        Design: Corner/state_machines/case_initial_state_referred
        """
        subject = create_provider("Subj Init", "SURGERY")
        resp = api_client.create_case(
            create_case_payload(subject_provider_id=subject["id"],
                                referral_source="INCIDENT_REPORT",
                                description="init case"),
            peer_review_coordinator_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "REFERRED"
        assert data["version"] == 1

    def test_case_get_not_found_returns_404(self, quality_director_headers):
        """PRD §2.8: "The 404 variant names the resource that failed to
        resolve: `ERR_PROVIDER_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`,
        `ERR_CASE_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
        `ERR_CONFLICT_NOT_FOUND`, `ERR_FOCUSED_REVIEW_NOT_FOUND`,
        `ERR_FOCUS_GROUP_NOT_FOUND`, or `ERR_MEMBERSHIP_NOT_FOUND`."

        Design: Corner/entities/case_get_not_found_returns_404
        """
        resp = api_client.get_case(NON_EXISTENT_UUID, quality_director_headers)
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_FOUND.value, expected_status=404)


class TestScreening:
    def test_screen_out_without_reason_rejected(self, quality_director_headers):
        """PRD §3.2: "A `decision` of `SCREEN_OUT` requires a
        `screened_out_reason` of `DUPLICATE`, `FRIVOLOUS`, `OUT_OF_SCOPE`, or
        `OTHER` — omitting it is rejected with
        `ERR_SCREEN_OUT_REASON_REQUIRED`".

        Design: Corner/validations/screen_out_missing_reason_rejected
        """
        subject = create_provider("Subj SO", "CARDIOLOGY")
        case = create_case(subject["id"], description="so case")
        resp = api_client.screen_case(case["id"], {"decision": "SCREEN_OUT"},
                                      quality_director_headers)
        validate_error(resp, ApiErrorId.ERR_SCREEN_OUT_REASON_REQUIRED.value,
                       expected_status=400)
        case_after = validate_success(api_client.get_case(case["id"], quality_director_headers))
        assert case_after["status"] == "REFERRED", "rejected screening must not move the case"

    def test_second_screen_on_screened_in_case_rejected(self, quality_director_headers):
        """PRD §3.2: "Both screening outcomes increment the case's `version`
        and refresh `updated_at`; both are legal only from `REFERRED`."
        PRD §2.8: "The target entity must be in a state from which the
        requested transition exists; otherwise `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/screen_on_screened_in_returns_invalid_state
        """
        subject = create_provider("Subj DS", "SURGERY")
        case = create_case(subject["id"], description="double screen")
        screen_case_in(case["id"])
        resp = api_client.screen_case(
            case["id"], {"decision": "SCREEN_OUT", "screened_out_reason": "OTHER"},
            quality_director_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
        case_after = validate_success(api_client.get_case(case["id"], quality_director_headers))
        assert case_after["status"] == "SCREENED_IN"
        assert case_after["screened_out_reason"] is None

    def test_assignment_on_terminal_case_returns_already_terminal(
            self, quality_director_headers, peer_review_coordinator_headers):
        """PRD §3.2: "`SCREENED_OUT` is one of the case's three terminal
        states, alongside `CLOSED` and `EXTERNAL_REVIEW`, and any further
        action attempted on a terminal case is rejected with
        `ERR_ALREADY_TERMINAL`."

        Design: Corner/state_machines/action_on_terminal_case_returns_already_terminal
        """
        subject = create_provider("Subj Term", "SURGERY")
        member = seat_member(create_provider("Rev B", "SURGERY")["id"], "MEMBER")
        case = create_case(subject["id"], description="terminal case")
        screened = validate_success(api_client.screen_case(
            case["id"], {"decision": "SCREEN_OUT", "screened_out_reason": "OUT_OF_SCOPE"},
            quality_director_headers))
        resp = api_client.create_assignment(
            case["id"],
            {"reviewer_id": member["id"], "expected_case_version": screened["version"]},
            peer_review_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL.value, expected_status=409)


class TestCaseListing:
    def test_case_list_filter_by_status(self, quality_director_headers):
        """PRD §3.7: "Cases can be listed with filters on `status`,
        `subject_provider_id`, and `focus_group_id`, which is how a focus
        group's stamped case list is assembled."

        Design: Corner/endpoints/case_list_filter_by_status
        """
        subject = create_provider("Subj Filt", "SURGERY")
        case1 = create_case(subject["id"], description="filter case 1")
        case2 = create_case(subject["id"], referred_at="2026-07-21T00:00:00Z",
                            description="filter case 2")
        screen_case_in(case2["id"])

        in_data, in_meta = validate_paginated(
            api_client.list_cases(quality_director_headers, params={"status": "SCREENED_IN"}))
        assert [c["id"] for c in in_data] == [case2["id"]]
        assert in_meta["total_count"] == 1

        ref_data, ref_meta = validate_paginated(
            api_client.list_cases(quality_director_headers, params={"status": "REFERRED"}))
        assert [c["id"] for c in ref_data] == [case1["id"]]
        assert ref_meta["total_count"] == 1


class TestReferralCooldown:
    def _screened_out_subject(self):
        subject = create_provider("Subj Nineteen", "CARDIOLOGY")
        case = create_case(subject["id"], referral_source="PATIENT_COMPLAINT",
                           description="first referral")
        return subject, case

    def test_referral_inside_thirty_day_cooldown_rejected(self, peer_review_coordinator_headers):
        """PRD §3.2: "If that case exists and its `screened_out_at` is
        strictly more recent than the instant thirty days before the current
        logical time, the referral is rejected with
        `ERR_DUPLICATE_REFERRAL_WINDOW` (409)."

        Design: Difficulty/resource_temporal_overlap/referral_cooldown_minimum_gap_semantics
        """
        subject, case = self._screened_out_subject()
        screened = validate_success(api_client.screen_case(
            case["id"], {"decision": "SCREEN_OUT", "screened_out_reason": "DUPLICATE"},
            TEST_QD))
        assert_instant_equals(screened["screened_out_at"], "2026-08-01T00:00:00Z")

        set_clock(COOLDOWN_DAY_29)  # 29 days after the screen-out
        resp = api_client.create_case(
            create_case_payload(subject_provider_id=subject["id"],
                                referral_source="STAFF_REFERRAL",
                                referred_at="2026-08-29T00:00:00Z",
                                description="too-early re-referral"),
            peer_review_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REFERRAL_WINDOW.value, expected_status=409)

    def test_referral_exactly_thirty_days_after_screen_out_allowed(
            self, peer_review_coordinator_headers):
        """PRD §3.2: "A referral made exactly thirty days after the screen-out
        — `screened_out_at` equal to the current logical time minus thirty
        days, to the second — is allowed."

        Design: Difficulty/resource_temporal_overlap/referral_cooldown_minimum_gap_semantics
        """
        subject, case = self._screened_out_subject()
        validate_success(api_client.screen_case(
            case["id"], {"decision": "SCREEN_OUT", "screened_out_reason": "DUPLICATE"},
            TEST_QD))

        set_clock(COOLDOWN_DAY_30)  # exactly 30 days after the screen-out
        resp = api_client.create_case(
            create_case_payload(subject_provider_id=subject["id"],
                                referral_source="STAFF_REFERRAL",
                                referred_at="2026-08-31T00:00:00Z",
                                description="boundary re-referral"),
            peer_review_coordinator_headers)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "REFERRED"
