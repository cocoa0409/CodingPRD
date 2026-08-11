"""Members, coverages, and enrollment-gating claims (PRD §3.2, §3.3)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_coverage,
    assert_member,
    create_config,
    create_coverage_payload,
    create_member,
    create_member_payload,
    create_verified_coverage,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ELIG = TEST_USERS["eligibility_analyst_headers"]
COB = TEST_USERS["cob_analyst_headers"]


class TestMemberBasics:
    def test_member_creation_with_defaults(self, api):
        """PRD §3.2: "A member begins in `ENROLLED` status and remains writable
        for COB purposes only while enrolled".
        PRD §3.2: "`custodial_decree_on_file` (default false) records that a court
        decree specifies which parent's plan is primary for a dependent child."
        PRD §3.2: "Medicare posture is captured by `medicare_entitlement_reason` —
        `NONE` (the default), `AGE`, `DISABILITY`, `ESRD`, or `ESRD_AND_AGE`".
        PRD §3.2: "The derived `other_coverage_count` reflects how many of the
        member's coverages are currently `VERIFIED`, excluding the plan's own
        coverage".

        Design: Corner/entities/member_creation_with_defaults
        """
        create_config()
        res = api.create_member(create_member_payload(), ELIG)
        member = validate_success(res, 201)
        assert_member(member)
        assert member["status"] == "ENROLLED"
        assert member["custodial_decree_on_file"] is False
        assert member["medicare_entitlement_reason"] == "NONE"
        assert member["employer_size"] == 50
        assert member["other_coverage_count"] == 0

    def test_member_get_not_found_returns_404(self, api):
        """PRD §2.8: "The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at
        the first identifier that does not resolve to an existing record, or where
        a nested child does not belong to the parent named in the path."

        Design: Corner/entities/member_get_not_found_returns_404
        """
        create_config()
        res = api.get_member(NON_EXISTENT_UUID, COB)
        validate_error(res, "ERR_NOT_FOUND", expected_status=404)

    def test_member_list_pagination(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned: it
        defaults to 10 when omitted, accepts a minimum of 1, and is bounded above
        at 100." and "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response
        envelope."

        Design: Corner/entities/member_list_pagination
        """
        create_config()
        for _ in range(3):
            get_success_data(api.create_member(create_member_payload(), ELIG))

        data, meta = validate_paginated(api.list_members(COB))
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert len(data) == 3

        data, meta = validate_paginated(api.list_members(COB, params={"limit": 2}))
        assert len(data) == 2
        assert meta["has_more"] is True

    def test_missing_required_field_rejected(self, api):
        """PRD §2.9: "Independently of these families, a request whose required
        input is missing or of the wrong type is rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/validations/missing_required_field_rejected
        """
        create_config()
        payload = create_member_payload()
        del payload["member_external_id"]
        res = api.create_member(payload, ELIG)
        validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)

    def test_error_member_disenrolled_blocks_writes(self, api):
        """PRD §3.2: "registering a coverage, verifying a coverage, drafting a
        primacy determination, responding to a survey, or submitting a claim all
        require the member to be `ENROLLED`, and any of them attempted against a
        disenrolled member is rejected with `ERR_MEMBER_DISENROLLED` (HTTP 409)."

        Design: Corner/errors/error_member_disenrolled_blocks_writes
        """
        create_config()
        member = create_member(employment_status="TERMINATED")
        get_success_data(api.disenroll_member(member["id"], ELIG))

        res = api.create_coverage(member["id"], create_coverage_payload(), COB)
        validate_error(res, "ERR_MEMBER_DISENROLLED", expected_status=409)


class TestCoverageRules:
    def test_coverage_invalid_window_rejected(self, api):
        """PRD §3.3: "requires `effective_from` to be strictly earlier than
        `effective_to` whenever an end date is present — an inverted window is
        rejected with `ERR_INVALID_COVERAGE_WINDOW` (HTTP 400)."

        Design: Corner/entities/coverage_invalid_window_rejected
        """
        create_config()
        member = create_member()
        res = api.create_coverage(
            member["id"],
            create_coverage_payload(effective_from="2026-12-31", effective_to="2026-01-01"),
            COB,
        )
        validate_error(res, "ERR_INVALID_COVERAGE_WINDOW", expected_status=400)

    def test_coverage_initial_state_pending_verification(self, api):
        """PRD §3.3: "A new coverage begins in `PENDING_VERIFICATION` and is
        decided by a `COBAnalyst`."

        Design: Corner/state_machines/coverage_initial_state_pending_verification
        """
        create_config()
        member = create_member()
        res = api.create_coverage(member["id"], create_coverage_payload(), COB)
        coverage = validate_success(res, 201)
        assert_coverage(coverage)
        assert coverage["verification_status"] == "PENDING_VERIFICATION"

    def test_coverage_terminal_lockdown(self, api):
        """PRD §2.9: "Whether the entity is in a state from which the requested
        transition is valid (`ERR_INVALID_STATE`)." and PRD §3.3: "On successful
        verification the coverage transitions from `PENDING_VERIFICATION` to
        `VERIFIED`".

        Design: Corner/state_machines/coverage_terminal_lockdown
        """
        create_config()
        member = create_member()
        coverage = create_verified_coverage(member["id"])
        assert coverage["verification_status"] == "VERIFIED"

        res = api.verify_coverage(member["id"], coverage["id"], COB)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_member_other_coverage_count_reconciled(self, api):
        """PRD §3.3: "the member's `other_coverage_count` is recomputed (counting
        only `VERIFIED` coverages and excluding `OUR_PLAN` ones)".

        Design: Corner/cross_cutting_complexity_layers/member_other_coverage_count_reconciled
        """
        create_config()
        member = create_member()
        create_verified_coverage(member["id"], payer_id="A", plan_name="A")
        create_verified_coverage(
            member["id"], payer_id="B", plan_name="B", coverage_kind="MEDICAID",
            subscriber_relationship="SELF", verification_source="MEMBER_SURVEY",
        )
        fetched = validate_success(api.get_member(member["id"], COB), 200)
        assert fetched["other_coverage_count"] == 2


class TestOurPlanUniqueness:
    def test_second_our_plan_overlapping_window_rejected(self, api):
        """PRD §3.3: "at most one `OUR_PLAN` coverage per member may be `VERIFIED`
        at any time, and verifying a second is rejected with
        `ERR_DUPLICATE_OUR_PLAN` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/coverage_window_overlap_our_plan_uniqueness
        """
        create_config()
        member = create_member()
        first = create_verified_coverage(
            member["id"], payer_id="OWN", plan_name="Own A", coverage_kind="OUR_PLAN",
            subscriber_relationship="SELF", policy_holder_dob=member["date_of_birth"],
            effective_from="2026-01-01", effective_to="2026-12-31",
            verification_source="ELIGIBILITY_MATCH",
        )
        assert first["verification_status"] == "VERIFIED"

        second = create_verified_coverage(
            member["id"], verify=False, payer_id="OWN", plan_name="Own B",
            coverage_kind="OUR_PLAN", subscriber_relationship="SELF",
            policy_holder_dob=member["date_of_birth"], effective_from="2026-06-01",
            verification_source="ELIGIBILITY_MATCH",
        )
        res = api.verify_coverage(member["id"], second["id"], COB)
        validate_error(res, "ERR_DUPLICATE_OUR_PLAN", expected_status=409)

    def test_second_our_plan_identical_window_rejected(self, api):
        """PRD §3.3: "at most one `OUR_PLAN` coverage per member may be `VERIFIED`
        at any time, and verifying a second is rejected with
        `ERR_DUPLICATE_OUR_PLAN` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/coverage_window_overlap_our_plan_uniqueness
        """
        create_config()
        member = create_member()
        create_verified_coverage(
            member["id"], payer_id="OWN", plan_name="Own A", coverage_kind="OUR_PLAN",
            subscriber_relationship="SELF", policy_holder_dob=member["date_of_birth"],
            verification_source="ELIGIBILITY_MATCH",
        )
        second = create_verified_coverage(
            member["id"], verify=False, payer_id="OWN", plan_name="Own B",
            coverage_kind="OUR_PLAN", subscriber_relationship="SELF",
            policy_holder_dob=member["date_of_birth"],
            verification_source="ELIGIBILITY_MATCH",
        )
        res = api.verify_coverage(member["id"], second["id"], COB)
        validate_error(res, "ERR_DUPLICATE_OUR_PLAN", expected_status=409)
