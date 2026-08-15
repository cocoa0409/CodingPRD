"""Sublets and alterations: the 15% sublet fee, the good-standing gate, the
mandatory owner-occupancy gap, alteration window overlap, and the safety-first
validation priority on alteration submission."""
from test_helpers import (
    OFFICER,
    ApiErrorId,
    approve_alteration,
    approve_sublet,
    assert_alteration_agreement,
    assert_sublet_agreement,
    charge_for_month,
    create_alteration,
    create_sublet,
    get_charge,
    get_shareholder,
    make_shareholder_headers,
    post_payment,
    setup_approved_schedule,
    setup_completed_sublet,
    setup_coop_with_owner,
    setup_delinquent_shareholder,
    submit_alteration,
    submit_sublet,
    validate_error,
    validate_success,
)


class TestSubletFee:
    def test_sublet_fee_is_fifteen_percent_of_base_maintenance(self, api):
        """PRD §3.7: "Approval comes from a passed resolution of kind
        `APPROVE_SUBLET`, which moves the agreement from `SUBMITTED` to
        `APPROVED` and prices the monthly sublet fee: `monthly_sublet_fee_cents`
        is fifteen percent of the unit's current base maintenance — the
        `base_amount_cents` of the unit's charge for the billing month current
        at approval, or zero if no such charge exists yet — rounded half-up to
        whole cents."

        Design: Corner/calculations/sublet_fee_is_15_percent_of_base
        """
        env = setup_approved_schedule(annual_budget_cents=1200000)
        coop_id = env["coop"]["id"]
        # Monthly base = round_half_up(1200000 / 12) = 100000 for the sole unit.
        august = charge_for_month(coop_id, "2026-08", env["unit"]["id"])
        assert august["base_amount_cents"] == 100000

        sublet = create_sublet(coop_id, env["unit"]["id"], env["owner"]["id"],
                               "2026-09-01T00:00:00Z", "2027-09-01T00:00:00Z")
        submit_sublet(coop_id, sublet["id"], env["owner"]["id"])
        approved = approve_sublet(coop_id, sublet["id"])
        assert approved["sublet_status"] == "APPROVED"
        # round_half_up(100000 * 1500 / 10000) = 15000
        assert approved["monthly_sublet_fee_cents"] == 15000


class TestSubletGoodStandingGate:
    def test_delinquent_shareholder_cannot_submit_sublet(self, api):
        """PRD §3.7: "Submitting the sublet is the owner's act and
        carries the house policy's full battery of checks. The caller's
        `X-User-ID` must equal the agreement's `shareholder_id`, and the
        shareholder must be in `GOOD_STANDING`."
        PRD §2.9: "every referenced entity exists and is in a compatible
        state: the selling shareholder is in `GOOD_STANDING`, the schedule being
        approved is still `DRAFT`, panel members are not the certifying agent;
        failure yields `ERR_CROSS_ENTITY_VIOLATION` (HTTP 422)".

        Design: Difficulty/cross_entity_state_dependency/sublet_submission_requires_good_standing
        """
        env = setup_delinquent_shareholder()
        coop_id = env["coop"]["id"]
        owner_id = env["owner"]["id"]
        assert get_shareholder(coop_id, owner_id)["standing"] == "DELINQUENT"

        sublet = create_sublet(coop_id, env["unit"]["id"], owner_id,
                               "2027-01-01T00:00:00Z", "2028-01-01T00:00:00Z")
        resp = api.submit_sublet(coop_id, sublet["id"],
                                 make_shareholder_headers(owner_id))
        assert resp.status_code in (409, 422), (
            f"delinquent owner's submit must fail, got {resp.status_code}")
        body = resp.json()
        assert body["data"]["error_id"] in (
            ApiErrorId.ERR_CROSS_ENTITY_VIOLATION, ApiErrorId.ERR_INVALID_STATE), \
            f"unexpected error_id {body['data']['error_id']}"
        still_draft = validate_success(
            api.get_sublet_agreement(coop_id, sublet["id"], OFFICER))
        assert still_draft["sublet_status"] == "DRAFT", "no transition occurred"

    def test_cured_shareholder_regains_sublet_submission(self, api):
        """PRD §3.4: "When the balance returns to zero — and no
        termination notice is outstanding — `standing` returns from
        `DELINQUENT` to `GOOD_STANDING`."
        PRD §3.7: "Submitting the sublet is the owner's act and carries
        the house policy's full battery of checks. The caller's `X-User-ID` must
        equal the agreement's `shareholder_id`, and the shareholder must be in
        `GOOD_STANDING`."

        Design: Difficulty/cross_entity_state_dependency/sublet_submission_requires_good_standing
        """
        env = setup_delinquent_shareholder()
        coop_id = env["coop"]["id"]
        owner_id = env["owner"]["id"]
        assert get_shareholder(coop_id, owner_id)["standing"] == "DELINQUENT"

        # Cure: pay the exact outstanding balance of the past-due charge.
        charge = get_charge(coop_id, env["charge"]["id"])
        post_payment(coop_id, charge["id"], owner_id, charge["outstanding_cents"])
        assert get_shareholder(coop_id, owner_id)["standing"] == "GOOD_STANDING"

        sublet = create_sublet(coop_id, env["unit"]["id"], owner_id,
                               "2027-01-01T00:00:00Z", "2028-01-01T00:00:00Z")
        submitted = submit_sublet(coop_id, sublet["id"], owner_id)
        assert submitted["sublet_status"] == "SUBMITTED"
        assert_sublet_agreement(submitted)


class TestSubletGapRule:
    def test_sublet_start_inside_gap_rejected(self, api):
        """PRD §3.7: "when the unit's `last_sublet_end_date` is set, the
        new `sublet_start_date` must fall on or after the date exactly
        `sublet_policy_gap_years` years later, enforcing the mandatory
        owner-occupancy gap."
        PRD §3.7: "the policy-specific breaches carry the dedicated code
        `ERR_SUBLET_POLICY_VIOLATION` (HTTP 422)".

        Design: Difficulty/resource_temporal_overlap/sublet_overlap_with_gap_rule
        """
        env = setup_completed_sublet()
        coop_id = env["coop"]["id"]
        assert env["sublet1"]["sublet_status"] == "COMPLETED"
        # First sublet ran [2026-09-01, 2027-09-01) -> gap year requires start
        # on or after 2028-09-01. A 2028-06-01 start is inside the gap.
        assert env["unit"]["last_sublet_end_date"] is not None

        sublet2 = create_sublet(coop_id, env["unit"]["id"], env["owner"]["id"],
                                "2028-06-01T00:00:00Z", "2029-06-01T00:00:00Z",
                                subtenant_name="Second Tenant")
        resp = api.submit_sublet(coop_id, sublet2["id"],
                                 make_shareholder_headers(env["owner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SUBLET_POLICY_VIOLATION,
                       expected_status=422)

    def test_sublet_start_exactly_after_gap_permitted(self, api):
        """PRD §3.7: "when the unit's `last_sublet_end_date` is set, the
        new `sublet_start_date` must fall on or after the date exactly
        `sublet_policy_gap_years` years later, enforcing the mandatory
        owner-occupancy gap."

        Design: Difficulty/resource_temporal_overlap/sublet_overlap_with_gap_rule
        """
        env = setup_completed_sublet()
        coop_id = env["coop"]["id"]
        assert env["sublet1"]["sublet_status"] == "COMPLETED"
        # Boundary: start exactly last_sublet_end_date + 1 gap year.
        sublet2 = create_sublet(coop_id, env["unit"]["id"], env["owner"]["id"],
                                "2028-09-01T00:00:00Z", "2029-09-01T00:00:00Z",
                                subtenant_name="Second Tenant")
        submitted = submit_sublet(coop_id, sublet2["id"], env["owner"]["id"])
        assert submitted["sublet_status"] == "SUBMITTED"


class TestAlterationWindowOverlap:
    def _setup_approved_alteration(self, api):
        env = setup_coop_with_owner()
        coop_id = env["coop"]["id"]
        alt1 = create_alteration(coop_id, env["unit"]["id"], env["owner"]["id"],
                                 "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z",
                                 scope_description="Kitchen",
                                 contractor_name="Ace",
                                 contractor_bid_cents=5000000)
        submit_alteration(coop_id, alt1["id"], env["owner"]["id"])
        alt1 = approve_alteration(coop_id, alt1["id"])
        assert alt1["alteration_status"] == "APPROVED"
        return env, alt1

    def test_overlapping_alteration_window_rejected(self, api):
        """PRD §3.8: "The window must be well ordered, and no other
        alteration for the same unit in `APPROVED` or `IN_PROGRESS` status may
        overlap it — overlaps are rejected with `ERR_TEMPORAL_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/alteration_overlap_pure_interval_no_gap
        """
        env, _alt1 = self._setup_approved_alteration(api)
        coop_id = env["coop"]["id"]
        # Overlaps the APPROVED [2026-09-01, 2026-10-01) window by 15 days.
        alt2 = create_alteration(coop_id, env["unit"]["id"], env["owner"]["id"],
                                 "2026-09-15T00:00:00Z", "2026-10-15T00:00:00Z",
                                 scope_description="Bathroom",
                                 contractor_name="Beta",
                                 contractor_bid_cents=3000000)
        resp = api.submit_alteration(coop_id, alt2["id"],
                                     make_shareholder_headers(env["owner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_CONFLICT, expected_status=422)

    def test_disjoint_alteration_window_permitted(self, api):
        """PRD §3.8: "The window must be well ordered, and no other
        alteration for the same unit in `APPROVED` or `IN_PROGRESS` status may
        overlap it — overlaps are rejected with `ERR_TEMPORAL_CONFLICT`."
        PRD §3.8: "A successful submission moves the agreement from
        `DRAFT` to `SUBMITTED` and computes the refundable
        `security_deposit_cents`: the greater of five percent of the contractor
        bid — rounded up to whole cents — and 500,000 cents (five thousand
        dollars)."

        Design: Difficulty/resource_temporal_overlap/alteration_overlap_pure_interval_no_gap
        """
        env, _alt1 = self._setup_approved_alteration(api)
        coop_id = env["coop"]["id"]
        # Clearly disjoint from the APPROVED [2026-09-01, 2026-10-01) window.
        alt2 = create_alteration(coop_id, env["unit"]["id"], env["owner"]["id"],
                                 "2026-11-01T00:00:00Z", "2026-12-01T00:00:00Z",
                                 scope_description="Bathroom",
                                 contractor_name="Beta",
                                 contractor_bid_cents=3000000)
        submitted = submit_alteration(coop_id, alt2["id"], env["owner"]["id"])
        assert submitted["alteration_status"] == "SUBMITTED"
        # max(5% of 3000000, 500000) = max(150000, 500000) = 500000
        assert submitted["security_deposit_cents"] == 500000
        assert_alteration_agreement(submitted)


class TestAlterationSubmissionPriority:
    def test_safety_violation_reported_before_referential_violation(self, api):
        """PRD §2.9: "When several checks could fail on the same request,
        the server reports only the earliest failure, evaluating checks in this
        fixed priority order" — alteration safety (priority 6, yielding
        `ERR_ALTERATION_SAFETY_VIOLATION` (HTTP 422)) precedes cross-entity
        referential integrity (priority 7, yielding
        `ERR_CROSS_ENTITY_VIOLATION` (HTTP 422)).
        PRD §3.8: "The contractor's coverage must be at least 100,000,000
        cents (one million dollars); short coverage is rejected with
        `ERR_ALTERATION_SAFETY_VIOLATION` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_alteration_submit
        """
        env = setup_delinquent_shareholder()
        coop_id = env["coop"]["id"]
        owner_id = env["owner"]["id"]
        assert get_shareholder(coop_id, owner_id)["standing"] == "DELINQUENT"

        # Both violations: insurance far below the minimum AND owner delinquent.
        alteration = create_alteration(
            coop_id, env["unit"]["id"], owner_id,
            "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z",
            contractor_insurance_cents=100)
        resp = api.submit_alteration(coop_id, alteration["id"],
                                     make_shareholder_headers(owner_id))
        validate_error(resp, ApiErrorId.ERR_ALTERATION_SAFETY_VIOLATION,
                       expected_status=422)

    def test_short_contractor_insurance_rejected(self, api):
        """PRD §3.8: "The contractor's coverage must be at least
        100,000,000 cents (one million dollars); short coverage is rejected with
        `ERR_ALTERATION_SAFETY_VIOLATION` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_alteration_submit
        """
        env = setup_coop_with_owner()
        coop_id = env["coop"]["id"]
        assert get_shareholder(coop_id, env["owner"]["id"])["standing"] == \
            "GOOD_STANDING"
        alteration = create_alteration(
            coop_id, env["unit"]["id"], env["owner"]["id"],
            "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z",
            contractor_insurance_cents=99999999)  # one cent below $1M
        resp = api.submit_alteration(coop_id, alteration["id"],
                                     make_shareholder_headers(env["owner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_ALTERATION_SAFETY_VIOLATION,
                       expected_status=422)
