"""Opening cancellation cases: ground/role gates, statutory floors computed
at creation, open-case exclusivity, and the optimistic-concurrency guard.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_cancellation_case,
    attach_interest,
    cancel_policy_effective,
    create_cancellation_case_payload,
    create_holder,
    get_policy,
    issue_policy,
    create_active_profile,
    make_compliance_officer_headers,
    make_policyholder_headers,
    make_underwriter_headers,
    open_cancellation_case,
    setup_active_policy,
    api_client,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx

OFFICER = TEST_USERS["compliance_officer_headers"]
UNDERWRITER = TEST_USERS["underwriter_headers"]


class TestGroundAndRoleGates:
    def test_ground_role_mismatch_in_both_directions(self, api):
        """PRD §3.3: "A `ground_code` of `INSURED_REQUEST` may be submitted
        only by the `Policyholder`; the insurer-initiated grounds —
        `NONPAYMENT`, `MATERIAL_MISREPRESENTATION`, `SUBSTANTIAL_CHANGE_IN_RISK`,
        and `LICENSE_SUSPENSION` — may be submitted only by an `Underwriter`.
        Crossing that line is rejected with `ERR_GROUND_ROLE_MISMATCH`."

        Design: Corner/validations/ground_role_mismatch_insured_request_by_underwriter
        """
        fx.set_clock("2026-08-01T00:00:00Z")
        profile = create_active_profile("WI")
        holder1 = create_holder(full_name="Wi One", email="wi1@x.com")
        holder2 = create_holder(full_name="Wi Two", email="wi2@x.com")
        policy1 = issue_policy(profile["id"], holder1["id"], "P-WI-1", total_premium_cents=10000)
        policy2 = issue_policy(profile["id"], holder2["id"], "P-WI-2", total_premium_cents=10000)

        # Underwriter may not file INSURED_REQUEST.
        resp = api.create_cancellation_case(
            create_cancellation_case_payload(
                policy1["id"], policy1["version"], ground_code="INSURED_REQUEST"
            ),
            UNDERWRITER,
        )
        validate_error(resp, ApiErrorId.ERR_GROUND_ROLE_MISMATCH)

        # Policyholder may not file an insurer-initiated ground.
        resp = api.create_cancellation_case(
            create_cancellation_case_payload(
                policy2["id"], policy2["version"], ground_code="NONPAYMENT"
            ),
            make_policyholder_headers(holder2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_GROUND_ROLE_MISMATCH)

    def test_terminal_cancelled_policy_rejects_new_cancellation_case(self, api):
        """PRD §3.3: "The policy must be `ACTIVE` — opening a case against a
        policy in any other status fails with `ERR_POLICY_NOT_ACTIVE` — and at
        most one cancellation case may be open per policy at a time."

        Design: Corner/state_machines/terminal_cancelled_policy_rejects_new_cancellation_case
        """
        bundle = cancel_policy_effective(
            "LA",
            request_clock="2026-08-01T00:00:00Z",
            scheduled_effective_date="2026-08-20",
            mailed_on_date="2026-08-01",
            policy_number="P-LA-1",
        )
        policy = bundle["policy"]
        assert policy["status"] == "CANCELLED"

        resp = api.create_cancellation_case(
            create_cancellation_case_payload(policy["id"], policy["version"], ground_code="NONPAYMENT"),
            UNDERWRITER,
        )
        validate_error(resp, ApiErrorId.ERR_POLICY_NOT_ACTIVE)


class TestWithdrawalGate:
    def test_withdraw_by_non_requester_role_forbidden(self, api):
        """PRD §3.5: "The actor's role must match the case's recorded
        `requested_by_role` — an underwriter-opened case may be withdrawn only
        by an `Underwriter`, a policyholder-opened case only by the
        `Policyholder` — or the attempt is rejected with
        `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/state_machines/withdraw_by_non_requester_role_forbidden
        """
        _profile, holder, policy = setup_active_policy("NJ", clock="2026-08-01T00:00:00Z")
        case = open_cancellation_case(policy, ground_code="NONPAYMENT")

        resp = api.withdraw_cancellation_case(case["id"], make_policyholder_headers(holder["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

        current = fx.get_cancellation_case(case["id"])
        assert current["status"] == "PENDING_APPROVAL"


class TestEarliestEffectiveDate:
    def test_notice_window_uses_ground_tier_constants(self, api):
        """PRD §3.3: "The base tier is the profile's `nonpayment_notice_days`
        when the ground is `NONPAYMENT`, and the profile's
        `other_grounds_notice_days` for every other ground — including
        `INSURED_REQUEST`." With no insured interests the floor is the
        request date plus the base tier.

        Design: Corner/calculations/notice_window_uses_nonpayment_tier_for_nonpayment_ground
        """
        fx.set_clock("2026-08-05T00:00:00Z")
        profile = create_active_profile(
            "SD", permissible_grounds=["NONPAYMENT", "MATERIAL_MISREPRESENTATION"]
        )
        holder1 = create_holder(full_name="Sd One", email="sd1@x.com")
        holder2 = create_holder(full_name="Sd Two", email="sd2@x.com")
        policy1 = issue_policy(profile["id"], holder1["id"], "P-SD-1", total_premium_cents=10000)
        policy2 = issue_policy(profile["id"], holder2["id"], "P-SD-2", total_premium_cents=10000)

        case_np = open_cancellation_case(policy1, ground_code="NONPAYMENT")
        case_mm = open_cancellation_case(policy2, ground_code="MATERIAL_MISREPRESENTATION")

        assert case_np["earliest_effective_date"] == "2026-08-15", (
            f"NONPAYMENT floor = requested 2026-08-05 + nonpayment_notice_days 10; "
            f"got {case_np['earliest_effective_date']}"
        )
        assert case_mm["earliest_effective_date"] == "2026-09-04", (
            f"other grounds floor = requested 2026-08-05 + other_grounds_notice_days 30; "
            f"got {case_mm['earliest_effective_date']}"
        )

    def test_notice_window_mortgagee_dominates_nonpayment_tier(self, api):
        """PRD §3.3: "When the policy carries at least one insured interest,
        each such interest is owed the profile's `mortgagee_notice_days`, and
        the floor becomes the `requested_on_date` plus the greater of the base
        tier and `mortgagee_notice_days`; with no interests on the policy, the
        floor is simply the `requested_on_date` plus the base tier."

        Design: Difficulty/combinatorial_formula/notice_window_max_across_ground_and_recipients
        """
        fx.set_clock("2026-08-05T00:00:00Z")
        profile = create_active_profile(
            "OR", permissible_grounds=["NONPAYMENT", "MATERIAL_MISREPRESENTATION"]
        )
        holder = create_holder(full_name="N One", email="n1@x.com")
        policy = issue_policy(profile["id"], holder["id"], "P-N-1", total_premium_cents=50000)
        attach_interest(policy["id"], interest_type="MORTGAGEE", institution_name="Bank 1")

        case = open_cancellation_case(policy, ground_code="NONPAYMENT")
        # max(nonpayment 10, mortgagee 45) = 45 days from 2026-08-05.
        assert case["earliest_effective_date"] == "2026-09-19", (
            f"interest-owed 45 days must dominate the 10-day nonpayment tier; "
            f"got {case['earliest_effective_date']}"
        )

    def test_notice_window_mortgagee_dominates_other_grounds_tier(self, api):
        """PRD §3.3: "When the policy carries at least one insured interest,
        each such interest is owed the profile's `mortgagee_notice_days`, and
        the floor becomes the `requested_on_date` plus the greater of the base
        tier and `mortgagee_notice_days`; with no interests on the policy, the
        floor is simply the `requested_on_date` plus the base tier."

        Design: Difficulty/combinatorial_formula/notice_window_max_across_ground_and_recipients
        """
        fx.set_clock("2026-08-05T00:00:00Z")
        profile = create_active_profile(
            "OR", permissible_grounds=["NONPAYMENT", "MATERIAL_MISREPRESENTATION"]
        )
        holder = create_holder(full_name="N Two", email="n2@x.com")
        policy = issue_policy(profile["id"], holder["id"], "P-N-2", total_premium_cents=50000)
        attach_interest(policy["id"], interest_type="MORTGAGEE", institution_name="Bank 2")

        case = open_cancellation_case(policy, ground_code="MATERIAL_MISREPRESENTATION")
        # max(other 30, mortgagee 45) = 45 days from 2026-08-05 — identical to
        # the NONPAYMENT case because the max is recipient-dominated.
        assert case["earliest_effective_date"] == "2026-09-19", (
            f"interest-owed 45 days must dominate the 30-day other-grounds tier; "
            f"got {case['earliest_effective_date']}"
        )


class TestOpenCaseExclusivity:
    def test_second_open_case_rejected(self, api):
        """PRD §3.3: "at most one cancellation case may be open per policy at
        a time, where open means `DRAFT`, `PENDING_APPROVAL`, `APPROVED`, or
        `NOTICE_SENT`; a second open case is rejected with
        `ERR_CANCELLATION_ALREADY_OPEN`."

        Design: Difficulty/resource_temporal_overlap/open_cancellation_case_excludes_second_case_same_policy
        """
        _profile, _holder, policy = setup_active_policy("NE", clock="2026-08-01T00:00:00Z")
        case1 = open_cancellation_case(policy, ground_code="NONPAYMENT")
        assert case1["status"] == "PENDING_APPROVAL"

        current = get_policy(policy["id"])
        resp = api.create_cancellation_case(
            create_cancellation_case_payload(policy["id"], current["version"], ground_code="NONPAYMENT"),
            UNDERWRITER,
        )
        validate_error(resp, ApiErrorId.ERR_CANCELLATION_ALREADY_OPEN)

    def test_new_case_permitted_after_first_withdrawn(self, api):
        """PRD §3.3: "at most one cancellation case may be open per policy at
        a time, where open means `DRAFT`, `PENDING_APPROVAL`, `APPROVED`, or
        `NOTICE_SENT`; a second open case is rejected with
        `ERR_CANCELLATION_ALREADY_OPEN`." A `WITHDRAWN` case is terminal, so
        the occupation releases.

        Design: Difficulty/resource_temporal_overlap/open_cancellation_case_excludes_second_case_same_policy
        """
        _profile, _holder, policy = setup_active_policy("NE", clock="2026-08-01T00:00:00Z")
        case1 = open_cancellation_case(policy, ground_code="NONPAYMENT")

        current = get_policy(policy["id"])
        blocked = api.create_cancellation_case(
            create_cancellation_case_payload(policy["id"], current["version"], ground_code="NONPAYMENT"),
            UNDERWRITER,
        )
        validate_error(blocked, ApiErrorId.ERR_CANCELLATION_ALREADY_OPEN)

        withdrawn = validate_success(api.withdraw_cancellation_case(case1["id"], UNDERWRITER))
        assert withdrawn["status"] == "WITHDRAWN"

        case2 = open_cancellation_case(get_policy(policy["id"]), ground_code="NONPAYMENT")
        assert_cancellation_case(case2)
        assert case2["status"] == "PENDING_APPROVAL"

        data, _meta = validate_paginated(
            api.list_cancellation_cases(
                OFFICER, params={"policy_id": policy["id"], "status": "PENDING_APPROVAL"}
            )
        )
        assert len(data) == 1, "at most one non-terminal case per policy at any time"


class TestGroundPermissibilityVsOpenCase:
    def test_unpermitted_ground_reported_even_when_case_already_open(self, api):
        """PRD §2.11: "Every request passes through the same ordered gauntlet,
        and a failure at any tier masks every later tier." Statutory ground
        permissibility (tier 6, `ERR_GROUND_NOT_PERMITTED_IN_STATE`) precedes
        uniqueness (tier 9, `ERR_CANCELLATION_ALREADY_OPEN`).
        PRD §3.3: "an insurer-initiated `ground_code` must appear in the
        pinned profile's `permissible_grounds`, while `INSURED_REQUEST` is
        always permitted; a ground the state does not allow mid-term is
        rejected with `ERR_GROUND_NOT_PERMITTED_IN_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_constraint_on_case_create
        """
        _profile, _holder, policy = setup_active_policy("MT", clock="2026-08-01T00:00:00Z")
        open_cancellation_case(policy, ground_code="NONPAYMENT")

        current = get_policy(policy["id"])
        resp = api.create_cancellation_case(
            create_cancellation_case_payload(
                policy["id"], current["version"], ground_code="LICENSE_SUSPENSION"
            ),
            UNDERWRITER,
        )
        validate_error(resp, ApiErrorId.ERR_GROUND_NOT_PERMITTED_IN_STATE)

    def test_unpermitted_ground_creates_no_second_case(self, api):
        """PRD §3.3: "an insurer-initiated `ground_code` must appear in the
        pinned profile's `permissible_grounds`, while `INSURED_REQUEST` is
        always permitted; a ground the state does not allow mid-term is
        rejected with `ERR_GROUND_NOT_PERMITTED_IN_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_constraint_on_case_create
        """
        profile, holder, policy = setup_active_policy("MT", clock="2026-08-01T00:00:00Z")
        open_cancellation_case(policy, ground_code="NONPAYMENT")

        current = get_policy(policy["id"])
        resp = api.create_cancellation_case(
            create_cancellation_case_payload(
                policy["id"], current["version"], ground_code="LICENSE_SUSPENSION"
            ),
            UNDERWRITER,
        )
        validate_error(resp, ApiErrorId.ERR_GROUND_NOT_PERMITTED_IN_STATE)

        data, _meta = validate_paginated(
            api.list_cancellation_cases(OFFICER, params={"policy_id": policy["id"]})
        )
        assert len(data) == 1, f"rejected create must not persist a case, got {len(data)}"

        # The same unpermitted ground is rejected on a clean policy too,
        # confirming the rejection is the ground rule, not the open-case rule.
        policy2 = issue_policy(profile["id"], holder["id"], "P-MT-2", total_premium_cents=30000)
        resp = api.create_cancellation_case(
            create_cancellation_case_payload(
                policy2["id"], policy2["version"], ground_code="LICENSE_SUSPENSION"
            ),
            UNDERWRITER,
        )
        validate_error(resp, ApiErrorId.ERR_GROUND_NOT_PERMITTED_IN_STATE)


class TestOptimisticConcurrencyOnCaseCreate:
    def test_case_create_bumps_policy_version_and_stale_write_rejected(self, api):
        """PRD §3.3: "A successfully opened case passes through its initial
        `DRAFT` status into `PENDING_APPROVAL`, records the `requested_on_date`
        as the current clock date and the `requested_by_role` as the caller's
        role, and bumps the policy's `version`."
        PRD §2.8: "If the supplied value does not equal the policy's current
        `version` at write time, the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_policy_version_increments_on_case_create
        """
        _profile, _holder, policy = setup_active_policy("PW", clock="2026-08-01T00:00:00Z")
        version_before = policy["version"]

        case = open_cancellation_case(policy, ground_code="NONPAYMENT")
        assert case["status"] == "PENDING_APPROVAL"

        after = get_policy(policy["id"])
        assert after["version"] == version_before + 1, (
            f"opening a case must bump the policy version by exactly one: "
            f"{version_before} -> {after['version']}"
        )

        # Clear the open case so the uniqueness tier passes and the OCC tier
        # is what fires on the stale write.
        validate_success(api.withdraw_cancellation_case(case["id"], UNDERWRITER))

        stale = api.create_cancellation_case(
            create_cancellation_case_payload(policy["id"], version_before, ground_code="NONPAYMENT"),
            UNDERWRITER,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
