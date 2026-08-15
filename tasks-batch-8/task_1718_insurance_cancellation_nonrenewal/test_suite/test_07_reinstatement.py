"""Reinstatement: lapse-day fee tiers, window boundaries, slot limits,
stale-version guard, expiry sweep, and the cancellation/reinstatement cycle.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_cancellation,
    approve_reinstatement,
    assert_reinstatement_request,
    cancel_policy_effective,
    create_active_profile,
    create_cancellation_case_payload,
    create_holder,
    create_reinstatement_payload,
    dispatch_cancellation_notices,
    dispatch_payload,
    issue_policy,
    make_policyholder_headers,
    open_cancellation_case,
    submit_reinstatement,
    get_policy,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx

OFFICER = TEST_USERS["compliance_officer_headers"]
UNDERWRITER = TEST_USERS["underwriter_headers"]


def _cancelled_policy(state_code, policy_number, premium_cents=30000, **profile_over):
    """A CANCELLED policy effective 2026-09-01 (case noticed 2026-08-10)."""
    return cancel_policy_effective(
        state_code,
        request_clock="2026-08-10T00:00:00Z",
        scheduled_effective_date="2026-09-01",
        mailed_on_date="2026-08-10",
        premium_cents=premium_cents,
        profile_over=profile_over,
        policy_number=policy_number,
    )


class TestFeeTierBoundaries:
    def test_lapse_at_tier1_boundary_free_and_tier2_edge_2500(self, api):
        """PRD §3.7: "A lapse of at most ten days carries no fee; a lapse of
        more than ten and at most thirty days carries a fee of 2,500 cents; a
        lapse of more than thirty days carries a fee of 5,000 cents. A lapse
        sitting exactly on a tier boundary falls into the lower tier — exactly
        ten days is free, exactly thirty days costs 2,500 cents."

        Design: Difficulty/dual_variant_calc/reinstatement_fee_tier_boundaries_same_window
        """
        b1 = _cancelled_policy("WA", "P-R-1", premium_cents=60000, max_reinstatements=3)
        b2 = _cancelled_policy("OR", "P-R-2", premium_cents=60000, max_reinstatements=3)

        fx.set_clock("2026-09-11T00:00:00Z")  # lapse 10 from 2026-09-01
        rr1 = submit_reinstatement(b1["policy"]["id"], b1["case"]["id"], b1["holder"]["id"])
        assert_reinstatement_request(rr1)
        assert rr1["lapse_days"] == 10
        assert rr1["reinstatement_fee_cents"] == 0, "lapse exactly 10 falls in the free tier"

        fx.set_clock("2026-09-12T00:00:00Z")  # lapse 11
        rr2 = submit_reinstatement(b2["policy"]["id"], b2["case"]["id"], b2["holder"]["id"])
        assert rr2["lapse_days"] == 11
        assert rr2["reinstatement_fee_cents"] == 2500, "lapse 11 falls in the 2,500-cent tier"

    def test_lapse_31_lands_in_tier3_5000(self, api):
        """PRD §3.7: "A lapse of at most ten days carries no fee; a lapse of
        more than ten and at most thirty days carries a fee of 2,500 cents; a
        lapse of more than thirty days carries a fee of 5,000 cents."

        Design: Difficulty/dual_variant_calc/reinstatement_fee_tier_boundaries_same_window
        """
        bundle = _cancelled_policy("WA", "P-R-3", premium_cents=60000, max_reinstatements=3)

        fx.set_clock("2026-10-02T00:00:00Z")  # lapse 31 from 2026-09-01
        rr = submit_reinstatement(bundle["policy"]["id"], bundle["case"]["id"], bundle["holder"]["id"])
        assert rr["lapse_days"] == 31
        assert rr["reinstatement_fee_cents"] == 5000, "lapse beyond 30 falls in the 5,000-cent tier"


class TestWindowBoundary:
    def test_reinstatement_on_exact_window_last_day_admitted(self, api):
        """PRD §3.7: "Eligibility is evaluated first: a `lapse_days` that
        exceeds the profile's `reinstatement_window_days` is rejected with
        `ERR_REINSTATEMENT_WINDOW_CLOSED`." With window 45 from a 2026-09-01
        cancellation, lapse 45 (2026-10-16) is admitted while lapse 46
        (2026-10-17) is rejected.

        Design: Difficulty/boundary_precision_check/reinstatement_at_exact_window_last_day_vs_empty_interest_notice_set
        """
        b1 = _cancelled_policy("WY", "P-WY-1")
        b2 = _cancelled_policy("VT", "P-WY-2")

        fx.set_clock("2026-10-16T00:00:00Z")  # lapse 45 == window 45
        rr1 = submit_reinstatement(b1["policy"]["id"], b1["case"]["id"], b1["holder"]["id"])
        assert rr1["status"] == "SUBMITTED"
        assert rr1["lapse_days"] == 45

        fx.set_clock("2026-10-17T00:00:00Z")  # lapse 46 > window 45
        current = get_policy(b2["policy"]["id"])
        resp = api.create_reinstatement_request(
            create_reinstatement_payload(b2["policy"]["id"], b2["case"]["id"], current["version"]),
            make_policyholder_headers(b2["holder"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REINSTATEMENT_WINDOW_CLOSED)

    def test_empty_notice_set_rejected(self, api):
        """PRD §3.4: "The set must contain exactly one notice addressed to the
        `POLICYHOLDER` plus exactly one notice per insured interest on the
        policy, each interest notice bearing a `recipient_kind` that matches
        that interest's `interest_type` — `MORTGAGEE`, `LIENHOLDER`, or
        `ADDITIONAL_INTEREST`; a missing policyholder notice or a missing
        per-interest notice fails with `ERR_NOTICE_SET_INCOMPLETE`."

        Design: Difficulty/boundary_precision_check/reinstatement_at_exact_window_last_day_vs_empty_interest_notice_set
        """
        fx.set_clock("2026-08-10T00:00:00Z")
        profile = create_active_profile("WY")
        holder = create_holder(full_name="Wy Three", email="wy3@x.com")
        policy = issue_policy(profile["id"], holder["id"], "P-WY-3", total_premium_cents=30000)
        case = open_cancellation_case(policy, ground_code="NONPAYMENT")
        approve_cancellation(case["id"], "2026-12-01")

        resp = api.dispatch_cancellation_notices(case["id"], dispatch_payload([]), UNDERWRITER)
        validate_error(resp, ApiErrorId.ERR_NOTICE_SET_INCOMPLETE)

        current = fx.get_cancellation_case(case["id"])
        assert current["status"] == "APPROVED"


class TestReinstatementLimit:
    def test_approval_beyond_max_reinstatements_rejected(self, api):
        """PRD §3.7: "Approval also re-verifies the policy's position — it
        must still be `CANCELLED` (`ERR_POLICY_NOT_CANCELLED`), and its
        `reinstatements_used` must still be below the pinned profile's
        `max_reinstatements`, since a policy that has exhausted its
        reinstatement slots fails with `ERR_REINSTATEMENT_LIMIT_REACHED`."

        Design: Corner/state_machines/reinstatement_limit_reached_on_third_attempt
        """
        bundle = cancel_policy_effective(
            "ND",
            request_clock="2026-08-01T00:00:00Z",
            scheduled_effective_date="2026-08-15",
            mailed_on_date="2026-08-01",
            profile_over={"max_reinstatements": 1, "reinstatement_window_days": 90},
            policy_number="P-ND-1",
        )
        policy_id = bundle["policy"]["id"]
        holder_id = bundle["holder"]["id"]

        fx.set_clock("2026-08-16T00:00:00Z")
        rr1 = submit_reinstatement(policy_id, bundle["case"]["id"], holder_id)
        approve_reinstatement(rr1["id"])
        mid = get_policy(policy_id)
        assert mid["status"] == "ACTIVE" and mid["reinstatements_used"] == 1

        case2 = open_cancellation_case(mid, ground_code="NONPAYMENT")
        approve_cancellation(case2["id"], "2026-09-01")
        dispatch_cancellation_notices(case2["id"], "2026-08-16", tracking_prefix="T-ND-2")
        fx.set_clock("2026-09-02T00:00:00Z")
        assert get_policy(policy_id)["status"] == "CANCELLED"

        rr2 = submit_reinstatement(policy_id, case2["id"], holder_id)
        assert rr2["status"] == "SUBMITTED"

        resp = api.approve_reinstatement_request(rr2["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_REINSTATEMENT_LIMIT_REACHED)

        final = get_policy(policy_id)
        assert final["status"] == "CANCELLED"
        assert final["reinstatements_used"] == 1
        assert fx.get_reinstatement_request(rr2["id"])["status"] == "SUBMITTED"


class TestStaleVersionOnReinstatement:
    def test_occ_stale_version_on_reinstatement_create(self, api):
        """PRD §2.8: "Opening a cancellation case and submitting a
        reinstatement request each require the caller to supply
        `expected_policy_version`, holding the `version` of the target Policy
        as the client last observed it. If the supplied value does not equal
        the policy's current `version` at write time, the request is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/endpoints/occ_stale_version_on_reinstatement_create
        """
        bundle = cancel_policy_effective(
            "MI",
            request_clock="2026-08-01T00:00:00Z",
            scheduled_effective_date="2026-08-20",
            mailed_on_date="2026-08-01",
            policy_number="P-MI-1",
        )
        fx.set_clock("2026-08-21T00:00:00Z")
        current = get_policy(bundle["policy"]["id"])
        assert current["status"] == "CANCELLED"

        resp = api.create_reinstatement_request(
            create_reinstatement_payload(
                current["id"], bundle["case"]["id"], current["version"] - 1
            ),
            make_policyholder_headers(bundle["holder"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        data, _meta = validate_paginated(
            api.list_reinstatement_requests(OFFICER, params={"policy_id": current["id"]})
        )
        assert data == [], "a stale write must not create a ReinstatementRequest"


class TestReinstatementExpirySweep:
    def test_reinstatement_request_auto_expires_after_window(self, api):
        """PRD §3.7: "The reinstatement expiry sweep moves a `SUBMITTED`
        request to `EXPIRED` once the current clock date passes the policy's
        `cancellation_effective_date` plus the profile's
        `reinstatement_window_days`." and "once more than thirty days have
        elapsed since the `cancellation_effective_date` without a
        reinstatement, the flag is set to true, marking the coverage lapse as
        hardened."

        Design: Corner/complexity_layers/reinstatement_request_auto_expires_after_window
        """
        bundle = _cancelled_policy("MH", "P-MH-1", premium_cents=10000)
        policy_id = bundle["policy"]["id"]

        fx.set_clock("2026-09-10T00:00:00Z")
        rr = submit_reinstatement(policy_id, bundle["case"]["id"], bundle["holder"]["id"])
        assert rr["status"] == "SUBMITTED"

        fx.set_clock("2026-10-17T00:00:00Z")  # 46 days past 2026-09-01; window 45
        expired = fx.get_reinstatement_request(rr["id"])
        assert expired["status"] == "EXPIRED"

        resp = api.approve_reinstatement_request(rr["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        policy = get_policy(policy_id)
        assert policy["status"] == "CANCELLED"
        assert policy["lapse_flag"] is True, "46 days without reinstatement hardens the lapse"


class TestCancellationReinstatementCycle:
    def _first_cycle(self):
        """GA policy: cancel effective 2026-09-01, reinstate 2026-09-05."""
        bundle = _cancelled_policy("GA", "P-CYC-1", premium_cents=60000)
        fx.set_clock("2026-09-05T00:00:00Z")
        rr = submit_reinstatement(bundle["policy"]["id"], bundle["case"]["id"], bundle["holder"]["id"])
        approve_reinstatement(rr["id"])
        return bundle, rr

    def test_first_cycle_restores_active_and_consumes_one_slot(self, api):
        """PRD §3.7: "An approved request moves `SUBMITTED → APPROVED`,
        returns the policy `CANCELLED → ACTIVE`, increments
        `reinstatements_used` by one, clears the `cancellation_effective_date`
        back to unset, posts a positive `REINSTATEMENT_FEE` ledger entry for
        the computed fee, and bumps the policy's `version`. The originating
        cancellation case deliberately stays `EFFECTIVE`, preserving the audit
        trail."

        Design: Difficulty/non_linear_state_machine/policy_cancellation_reinstatement_cycle
        """
        bundle, rr = self._first_cycle()
        policy = get_policy(bundle["policy"]["id"])
        assert policy["status"] == "ACTIVE"
        assert policy["reinstatements_used"] == 1
        assert policy["cancellation_effective_date"] is None

        case1 = fx.get_cancellation_case(bundle["case"]["id"])
        assert case1["status"] == "EFFECTIVE", "the audit trail survives the loop"
        assert fx.get_reinstatement_request(rr["id"])["status"] == "APPROVED"

    def test_second_cancellation_after_reinstatement_keeps_slot_count(self, api):
        """PRD §3.7: "An approved request moves `SUBMITTED → APPROVED`,
        returns the policy `CANCELLED → ACTIVE`, increments
        `reinstatements_used` by one, clears the `cancellation_effective_date`
        back to unset, posts a positive `REINSTATEMENT_FEE` ledger entry for
        the computed fee, and bumps the policy's `version`." The slot counter
        persists across cycles, so after a second cancellation the policy is
        `CANCELLED` with `reinstatements_used` still 1.

        Design: Difficulty/non_linear_state_machine/policy_cancellation_reinstatement_cycle
        """
        bundle, _rr = self._first_cycle()
        policy = get_policy(bundle["policy"]["id"])
        assert policy["reinstatements_used"] == 1

        case2 = open_cancellation_case(policy, ground_code="NONPAYMENT")
        approve_cancellation(case2["id"], "2026-10-01")
        dispatch_cancellation_notices(case2["id"], "2026-09-05", tracking_prefix="T-CYC-2")
        fx.set_clock("2026-10-01T00:00:00Z")

        final = get_policy(policy["id"])
        assert final["status"] == "CANCELLED"
        assert final["reinstatements_used"] == 1
        assert fx.get_cancellation_case(case2["id"])["status"] == "EFFECTIVE"
        assert fx.get_cancellation_case(bundle["case"]["id"])["status"] == "EFFECTIVE"
