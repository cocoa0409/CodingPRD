"""Hardship waivers: FULL/PARTIAL reduction math, criteria gates, appeal loop (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    factories,
    find_notice,
    get_estate_case,
    get_waiver,
    setup_estate_claim_filed,
    setup_pending_waiver,
    validate_error,
    validate_paginated,
    validate_success,
)

SUP1 = TEST_USERS["supervisor_headers"]
ERO = TEST_USERS["estate_officer_headers"]


class TestPartialReduction:
    def test_partial_reduction_nested_minmax_result(self, api):
        """PRD §3.7: "For a `PARTIAL` waiver, the computation runs in order: the exposed equity is the `homestead_value_cents` less the fifty-thousand-dollar homestead exemption, floored at zero; the collectible amount is the estate's `claim_outstanding_cents` less that exposed equity, again floored at zero; and `decided_reduction_cents` is the lesser of `requested_reduction_cents` and the collectible amount."

        Design: Difficulty/combinatorial_formula/hardship_partial_reduction_nested_minmax
        """
        # outstanding 4000000; exposed equity max(0, 7000000-5000000)=2000000;
        # collectible 4000000-2000000=2000000; decided = min(3000000, 2000000).
        ctx = setup_pending_waiver(
            lifetime_paid_cents=4000000,
            waiver_type="PARTIAL",
            household_income_annual_cents=4000000,
            homestead_value_cents=7000000,
            requested_reduction_cents=3000000,
        )
        approved = validate_success(
            api.approve_waiver(ctx["waiver"]["id"], SUP1), 200
        )
        assert approved["status"] == "APPROVED"
        assert approved["decided_reduction_cents"] == 2000000, (
            f"min(3000000, max(0, 4000000 - 2000000)) = 2000000, got {approved['decided_reduction_cents']}"
        )

    def test_partial_approval_leaves_estate_claim_filed(self, api):
        """PRD §3.7: "Approval subtracts the decided reduction from the estate's `claim_outstanding_cents`. A `FULL` approval zeroes the balance and moves the estate case from `CLAIM_FILED` to `WAIVED`; a `PARTIAL` approval leaves the estate case in `CLAIM_FILED` unless the reduction happens to drive the outstanding balance to exactly zero, in which case the case moves to `PAID`."

        Design: Difficulty/combinatorial_formula/hardship_partial_reduction_nested_minmax
        """
        ctx = setup_pending_waiver(
            lifetime_paid_cents=4000000,
            waiver_type="PARTIAL",
            household_income_annual_cents=4000000,
            homestead_value_cents=7000000,
            requested_reduction_cents=3000000,
        )
        validate_success(api.approve_waiver(ctx["waiver"]["id"], SUP1), 200)
        estate_case = get_estate_case(ctx["estate_case"]["id"])
        assert estate_case["claim_outstanding_cents"] == 2000000, (
            f"4000000 - 2000000 = 2000000, got {estate_case['claim_outstanding_cents']}"
        )
        assert estate_case["status"] == "CLAIM_FILED"


class TestFullWaiverCascade:
    def test_full_approval_decides_entire_outstanding(self, api):
        """PRD §3.7: "For a `FULL` waiver, `decided_reduction_cents` is the estate case's entire `claim_outstanding_cents` at the moment of approval."
        PRD §3.7: "A `FULL` approval zeroes the balance and moves the estate case from `CLAIM_FILED` to `WAIVED`"

        Design: Difficulty/transitive_cascade/waiver_full_approve_cascade_depth2
        """
        ctx = setup_pending_waiver(
            lifetime_paid_cents=4000000,
            waiver_type="FULL",
            household_income_annual_cents=2000000,
            homestead_value_cents=4000000,
        )
        approved = validate_success(
            api.approve_waiver(ctx["waiver"]["id"], SUP1), 200
        )
        assert approved["status"] == "APPROVED"
        assert approved["decided_reduction_cents"] == 4000000
        estate_case = get_estate_case(ctx["estate_case"]["id"])
        assert estate_case["status"] == "WAIVED"
        assert estate_case["claim_outstanding_cents"] == 0

    def test_full_approval_queues_estate_decision_notice(self, api):
        """PRD §3.7: "Either way an `ESTATE_DECISION_NOTICE` is queued per §2.11."
        PRD §2.11: "Five business events generate a CommunicationNotice to the member: lien filing, settlement acceptance, case resolution, estate claim filing, and every hardship-waiver decision. Each notice is created in `QUEUED` status, and its `due_date` is the creation calendar date plus thirty days — the member-communication deadline."

        Design: Difficulty/transitive_cascade/waiver_full_approve_cascade_depth2
        """
        ctx = setup_pending_waiver(
            lifetime_paid_cents=4000000,
            waiver_type="FULL",
            household_income_annual_cents=2000000,
            homestead_value_cents=4000000,
        )
        validate_success(api.approve_waiver(ctx["waiver"]["id"], SUP1), 200)
        notice = find_notice(
            "ESTATE_DECISION_NOTICE", estate_case_id=ctx["estate_case"]["id"]
        )
        assert notice["status"] == "QUEUED"
        assert notice["member_id"] == ctx["member"]["id"]
        assert notice["case_id"] is None


class TestHardshipCriteria:
    def test_full_waiver_at_exact_criteria_boundaries_approved(self, api):
        """PRD §3.7: "A `FULL` waiver additionally must satisfy the statutory hardship criteria: the `homestead_value_cents` must be at most 5,000,000 cents (fifty thousand dollars) and the `household_income_annual_cents` must be at most 3,000,000 cents (thirty thousand dollars); failing either prong rejects the approval with `ERR_HARDSHIP_CRITERIA_NOT_MET` (HTTP 409)."

        Design: Corner/calculations/hardship_full_criteria_inclusive_boundary
        """
        # Both prongs exactly at the cap: "at most" is inclusive.
        ctx = setup_pending_waiver(
            lifetime_paid_cents=4000000,
            waiver_type="FULL",
            household_income_annual_cents=3000000,
            homestead_value_cents=5000000,
        )
        approved = validate_success(
            api.approve_waiver(ctx["waiver"]["id"], SUP1), 200
        )
        assert approved["status"] == "APPROVED"
        assert approved["decided_reduction_cents"] == 4000000
        assert get_estate_case(ctx["estate_case"]["id"])["status"] == "WAIVED"

    def test_full_waiver_one_cent_over_income_limit_rejected(self, api):
        """PRD §3.7: "A `FULL` waiver additionally must satisfy the statutory hardship criteria: the `homestead_value_cents` must be at most 5,000,000 cents (fifty thousand dollars) and the `household_income_annual_cents` must be at most 3,000,000 cents (thirty thousand dollars); failing either prong rejects the approval with `ERR_HARDSHIP_CRITERIA_NOT_MET` (HTTP 409)."

        Design: Corner/validations/full_waiver_criteria_fail_rejected
        """
        ctx = setup_pending_waiver(
            lifetime_paid_cents=500000,
            waiver_type="FULL",
            household_income_annual_cents=3000001,
            homestead_value_cents=1000000,
        )
        resp = api.approve_waiver(ctx["waiver"]["id"], SUP1)
        validate_error(resp, ApiErrorId.ERR_HARDSHIP_CRITERIA_NOT_MET)
        assert get_waiver(ctx["waiver"]["id"])["status"] == "PENDING"


class TestAppealLoop:
    def test_denied_waiver_appeal_returns_to_pending(self, api):
        """PRD §3.7: "An `EstateRecoveryOfficer` may appeal a denied waiver once, moving it from `DENIED` back to `PENDING` and incrementing `appeal_count` by one; when `appeal_count` has already reached one, a further appeal is rejected with `ERR_APPEAL_LIMIT_REACHED` (HTTP 409)."

        Design: Corner/state_machines/waiver_appeal_loop_denied_to_pending
        """
        ctx = setup_pending_waiver(
            lifetime_paid_cents=4000000,
            waiver_type="PARTIAL",
            household_income_annual_cents=1000000,
            homestead_value_cents=1000000,
            requested_reduction_cents=500000,
        )
        denied = validate_success(api.deny_waiver(ctx["waiver"]["id"], SUP1), 200)
        assert denied["status"] == "DENIED"
        appealed = validate_success(api.appeal_waiver(ctx["waiver"]["id"], ERO), 200)
        assert appealed["status"] == "PENDING"
        assert appealed["appeal_count"] == 1

    def test_second_appeal_rejected_at_limit(self, api):
        """PRD §3.7: "when `appeal_count` has already reached one, a further appeal is rejected with `ERR_APPEAL_LIMIT_REACHED` (HTTP 409)."

        Design: Corner/state_machines/waiver_second_appeal_rejected
        """
        ctx = setup_pending_waiver(
            lifetime_paid_cents=4000000,
            waiver_type="FULL",
            household_income_annual_cents=1000000,
            homestead_value_cents=1000000,
        )
        waiver_id = ctx["waiver"]["id"]
        validate_success(api.deny_waiver(waiver_id, SUP1), 200)
        validate_success(api.appeal_waiver(waiver_id, ERO), 200)
        validate_success(api.deny_waiver(waiver_id, SUP1), 200)
        resp = api.appeal_waiver(waiver_id, ERO)
        validate_error(resp, ApiErrorId.ERR_APPEAL_LIMIT_REACHED)
        waiver = get_waiver(waiver_id)
        assert waiver["status"] == "DENIED"
        assert waiver["appeal_count"] == 1


class TestPendingWaiverUniqueness:
    def test_second_pending_waiver_rejected(self, api):
        """PRD §3.7: "An `EstateRecoveryOfficer` or `RecoverySupervisor` applies for a HardshipWaiver on an estate case in `CLAIM_FILED` status (otherwise `ERR_CLAIM_NOT_FILED`), and only one waiver may be pending at a time: if a waiver in `PENDING` status already exists on the estate case, the application is rejected with `ERR_WAIVER_PENDING_EXISTS` (HTTP 409)."

        Design: Corner/validations/second_pending_waiver_rejected
        """
        ctx = setup_estate_claim_filed(lifetime_paid_cents=500000)
        estate_case_id = ctx["estate_case"]["id"]
        validate_success(
            api.create_waiver(
                estate_case_id,
                factories.waiver_payload(
                    waiver_type="FULL",
                    household_income_annual_cents=1000000,
                    homestead_value_cents=1000000,
                ),
                ERO,
            ),
            201,
        )
        resp = api.create_waiver(
            estate_case_id,
            factories.waiver_payload(
                waiver_type="PARTIAL",
                household_income_annual_cents=1000000,
                homestead_value_cents=1000000,
                requested_reduction_cents=100000,
            ),
            ERO,
        )
        validate_error(resp, ApiErrorId.ERR_WAIVER_PENDING_EXISTS)
        data, meta = validate_paginated(
            api.list_waivers(ERO, params={"estate_case_id": estate_case_id})
        )
        assert meta["total_count"] == 1
